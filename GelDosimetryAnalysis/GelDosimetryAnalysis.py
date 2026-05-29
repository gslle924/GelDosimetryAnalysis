import os
import unittest
import numpy
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
import GelDosimetryAnalysisLogic
import DataProbeLib
import slicer.util
from DICOMLib import DICOMUtils
from slicer.util import VTKObservationMixin

#
# Gel dosimetry analysis slicelet
#
# Streamlined workflow end-user application based on 3D Slicer and SlicerRT to support
# 3D gel-based radiation dosimetry.
#
# The all-caps terms correspond to data objects in the gel dosimetry data flow diagram
# https://subversion.assembla.com/svn/slicerrt/trunk/GelDosimetryAnalysis/doc/GelDosimetryAnalysis_DataFlow.png
#

#
# GelDosimetryAnalysisSliceletWidget
#
class GelDosimetryAnalysisSliceletWidget:
  def __init__(self, parent=None):
    try:
      parent
      self.parent = parent

    except Exception as e:
      import traceback
      traceback.print_exc()
      logging.error("There is no parent to GelDosimetryAnalysisSliceletWidget!")

#
# SliceletMainFrame
# Handles the event when the slicelet is hidden (its window closed)
#
class SliceletMainFrame(qt.QDialog):
  def setSlicelet(self, slicelet):
    self.slicelet = slicelet

  def hideEvent(self, event):
    self.slicelet.disconnect()

    import gc
    refs = gc.get_referrers(self.slicelet)
    if len(refs) > 1:
      # logging.debug('Stuck slicelet references (' + repr(len(refs)) + '):\n' + repr(refs))
      pass

    slicer.gelDosimetrySliceletInstance = None
    self.slicelet = None
    self.deleteLater()

#
# GelDosimetryAnalysisSlicelet
#
class GelDosimetryAnalysisSlicelet(VTKObservationMixin):
  def __init__(self, parent, developerMode=False, widgetClass=None):
    VTKObservationMixin.__init__(self)
    # Set up main frame
    self.parent = parent
    self.parent.setLayout(qt.QHBoxLayout())

    self.layout = self.parent.layout()
    self.layout.setMargin(0)
    self.layout.setSpacing(0)

    self.sliceletPanel = qt.QFrame(self.parent)
    self.sliceletPanelLayout = qt.QVBoxLayout(self.sliceletPanel)
    self.sliceletPanelLayout.setMargin(4)
    self.sliceletPanelLayout.setSpacing(0)
    self.layout.addWidget(self.sliceletPanel,1)

    # Initiate and group together all panels
    self.step0_layoutSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_loadDataCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_registrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step3_doseCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step4_doseComparisonCollapsibleButton = ctk.ctkCollapsibleButton()
    self.stepT1_lineProfileCollapsibleButton = ctk.ctkCollapsibleButton()

    self.collapsibleButtonsGroup = qt.QButtonGroup()
    self.collapsibleButtonsGroup.addButton(self.step0_layoutSelectionCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step1_loadDataCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step2_registrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step3_doseCalibrationCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.step4_doseComparisonCollapsibleButton)
    self.collapsibleButtonsGroup.addButton(self.stepT1_lineProfileCollapsibleButton)

    self.step0_layoutSelectionCollapsibleButton.setProperty('collapsed', False)

    # Create module logic
    self.logic = GelDosimetryAnalysisLogic.GelDosimetryAnalysisLogic()

    # Set up constants
    self.igrtMarkupsFiducialNode_WithPlanName = "IGRT fiducials (IGRT to PLANNING)"
    self.planningMarkupsFiducialNodeName = "PLANNING fiducials"
    self.igrtMarkupsFiducialNode_WithMeasuredName = "IGRT fiducials (IGRT to MEASURED)"
    self.measuredMarkupsFiducialNodeName = "MEASURED fiducials"

    # Declare member variables (selected at certain steps and then from then on for the workflow)
    self.mode = None

    self.planningVolumeNode = None
    self.planDoseVolumeNode = None
    self.planStructuresNode = None
    self.igrtVolumeNode = None
    self.measuredVolumeNode = None
    self.calibrationVolumeNode = None

    self.igrtMarkupsFiducialNode_WithPlan = None
    self.planningMarkupsFiducialNode = None
    self.igrtMarkupsFiducialNode_WithMeasured = None
    self.measuredMarkupsFiducialNode = None
    self.calibratedMeasuredVolumeNode = None
    self.maskSegmentationNode = None
    self.maskSegmentID = None
    self.gammaVolumeNode = None

    # Get markups logic
    self.markupsLogic = slicer.modules.markups.logic()

    # Create or get fiducial nodes (IGRT to Planning)
    try:
      self.igrtMarkupsFiducialNode_WithPlan = slicer.util.getNode(self.igrtMarkupsFiducialNode_WithPlanName)
    except:
      igrtFiducialsNode1Id = self.markupsLogic.AddNewFiducialNode(self.igrtMarkupsFiducialNode_WithPlanName)
      self.igrtMarkupsFiducialNode_WithPlan = slicer.mrmlScene.GetNodeByID(igrtFiducialsNode1Id)
    try:
      self.planningMarkupsFiducialNode = slicer.util.getNode(self.planningMarkupsFiducialNodeName)
    except:
      measuredFiducialsNodeId = self.markupsLogic.AddNewFiducialNode(self.planningMarkupsFiducialNodeName)
      self.planningMarkupsFiducialNode = slicer.mrmlScene.GetNodeByID(measuredFiducialsNodeId)
    measuredFiducialsDisplayNode = self.planningMarkupsFiducialNode.GetDisplayNode()
    measuredFiducialsDisplayNode.SetSelectedColor(0, 0.9, 0.9)
    
    # Create or get fiducial nodes (IGRT to MEASURED)
    try:
      self.igrtMarkupsFiducialNode_WithMeasured = slicer.util.getNode(self.igrtMarkupsFiducialNode_WithMeasuredName)
    except:
      igrtFiducialsNode2Id = self.markupsLogic.AddNewFiducialNode(self.igrtMarkupsFiducialNode_WithMeasuredName)
      self.igrtMarkupsFiducialNode_WithMeasured = slicer.mrmlScene.GetNodeByID(igrtFiducialsNode2Id)
    try:
      self.measuredMarkupsFiducialNode = slicer.util.getNode(self.measuredMarkupsFiducialNodeName)
    except:
      measuredFiducialsNodeId = self.markupsLogic.AddNewFiducialNode(self.measuredMarkupsFiducialNodeName)
      self.measuredMarkupsFiducialNode = slicer.mrmlScene.GetNodeByID(measuredFiducialsNodeId)
    measuredFiducialsDisplayNode = self.measuredMarkupsFiducialNode.GetDisplayNode()
    measuredFiducialsDisplayNode.SetSelectedColor(0, 0.9, 0)

    # Turn on slice intersections in 2D viewers
    compositeNodes = slicer.util.getNodes("vtkMRMLSliceCompositeNode*")
    for compositeNode in compositeNodes.values():
      compositeNode.SetSliceIntersectionVisibility(1)

    # Add layout widget
    self.layoutWidget = slicer.qMRMLLayoutWidget()
    self.layoutWidget.setMRMLScene(slicer.mrmlScene)
    self.parent.layout().addWidget(self.layoutWidget,2)
    self.onViewSelect(0)

    # Create slice annotations for scalar bar support
    self.sliceAnnotations = DataProbeLib.SliceAnnotations(self.layoutWidget.layoutManager())
    self.sliceAnnotations.scalarBarEnabled = 0
    self.sliceAnnotations.updateSliceViewFromGUI()

    # Create line profile logic
    self.lineProfileLogic = GelDosimetryAnalysisLogic.LineProfileLogic()

    # Set up step panels
    self.setup_Step0_LayoutSelection()
    self.setup_Step1_LoadData()
    self.setup_Step2_Registration()
    self.setup_step3_DoseCalibration()
    self.setup_Step4_DoseComparison()
    self.setup_StepT1_lineProfileCollapsibleButton()

    if widgetClass:
      self.widget = widgetClass(self.parent)
    self.parent.show()
  
  #------------------------------------------------------------------------------
  # Disconnect all connections made to the slicelet to enable the garbage collector to destruct the slicelet object on quit
  def disconnect(self):
    self.step0_viewSelectorComboBox.disconnect('activated(int)', self.onViewSelect)
    self.step0_clinicalModeRadioButton.disconnect('toggled(bool)', self.onClinicalModeSelect)
    self.step0_preclinicalModeRadioButton.disconnect('toggled(bool)', self.onPreclinicalModeSelect)
    self.step1_showDicomBrowserButton.disconnect('clicked()', self.logic.onDicomLoad)
    self.step1_loadNonDicomDataButton.disconnect('clicked()', self.onLoadNonDicomData)
    self.step1_loadDataCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep1_LoadDataCollapsed)
    self.step2_registrationCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_RegistrationCollapsed)
    self.step2_1_registrationTypeAutomaticRadioButton.disconnect('toggled(bool)', self.onAutomaticPlanningToIGRTRegistrationToggled)
    self.step2_1_registerPlanningToIGRTButton.disconnect('clicked()', self.onPlanningToIGRTAutomaticRegistration)
    self.step2_1_translationSliders.disconnect('valuesChanged()', self.step2_1_rotationSliders.resetUnactiveSliders)
    self.step2_1_planningToIGRTRegistrationCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_1_PlanningToIGRTRegistrationSelected)
    self.step2_1_1_igrtFiducialSelectionCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_1_1_IGRTFiducialCollectionSelected)
    self.step2_1_2_planningFiducialSelectionCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_1_2_PlanningFiducialCollectionSelected)
    self.step2_1_3_registerPlanningToIGRTButton.disconnect('clicked()', self.onPlanningToIGRTLandmarkRegistration)
    self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_2_MeasuredDoseToIGRTRegistrationSelected)
    self.step2_2_registrationTypeAutomaticRadioButton.disconnect('toggled(bool)', self.onAutomaticMeasuredToIgrtRegistrationToggled)
    self.step2_2_registerMeasuredToIgrtAutomaticButton.disconnect('clicked()', self.onMeasuredToIgrtAutomaticRegistration)
    self.step2_2_translationSliders.disconnect('valuesChanged()', self.step2_2_rotationSliders.resetUnactiveSliders)
    self.step2_2_1_igrtFiducialSelectionCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_2_1_IGRTFiducialCollectionSelected)
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep2_2_2_MeasuredFiducialCollectionSelected)
    self.step2_2_3_registerMeasuredToIgrtButton.disconnect('clicked()', self.onMeasuredToIgrtRegistration)
    self.step3_1_pddLoadDataButton.disconnect('clicked()', self.onLoadPddDataRead)
    self.step3_1_alignCalibrationCurvesButton.disconnect('clicked()', self.onAlignCalibrationCurves)
    self.step3_1_xTranslationSpinBox.disconnect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_yScaleSpinBox.disconnect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_yTranslationSpinBox.disconnect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_computeDoseFromPddButton.disconnect('clicked()', self.onComputeDoseFromPdd)
    self.step3_1_calibrationRoutineCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep3_1_CalibrationRoutineSelected)
    self.step3_1_showDeltaRVsDoseCurveButton.disconnect('clicked()', self.onShowDeltaRVsDoseCurve)
    self.step3_1_removeSelectedPointsFromDeltaRVsDoseCurveButton.disconnect('clicked()', self.onRemoveSelectedPointsFromDeltaRVsDoseCurve)
    self.step3_1_fitPolynomialToDeltaRVsDoseCurveButton.disconnect('clicked()', self.onFitPolynomialToDeltaRVsDoseCurve)
    self.step3_2_exportCalibrationToCSV.disconnect('clicked()', self.onExportCalibration)
    self.step3_2_applyCalibrationButton.disconnect('clicked()', self.onApplyCalibration)
    self.step4_doseComparisonCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStep4_DoseComparisonSelected)
    self.step4_maskSegmentationSelector.disconnect('currentNodeChanged(vtkMRMLNode*)', self.onStep4_MaskSegmentationSelectionChanged)
    self.step4_maskSegmentationSelector.disconnect('currentSegmentChanged(QString)', self.onStep4_MaskSegmentSelectionChanged)
    self.step4_1_referenceDoseUseMaximumDoseRadioButton.disconnect('toggled(bool)', self.onUseMaximumDoseRadioButtonToggled)
    self.step4_1_computeGammaButton.disconnect('clicked()', self.onGammaDoseComparison)
    self.step4_1_showGammaReportButton.disconnect('clicked()', self.onShowGammaReport)
    self.stepT1_lineProfileCollapsibleButton.disconnect('contentsCollapsed(bool)', self.onStepT1_LineProfileSelected)
    self.stepT1_lineProfileLegendVisibilityCheckbox.disconnect('toggled(bool)', self.onLegendVisibilityToggled)
    self.stepT1_createLineProfileButton.disconnect('clicked(bool)', self.onCreateLineProfileButton)
    self.stepT1_inputRulerSelector.disconnect("currentNodeChanged(vtkMRMLNode*)", self.onSelectLineProfileParameters)
    self.stepT1_exportLineProfilesToCSV.disconnect('clicked()', self.onExportLineProfiles)

  #------------------------------------------------------------------------------
  def setup_Step0_LayoutSelection(self):
    # Layout selection step
    self.step0_layoutSelectionCollapsibleButton.setProperty('collapsedHeight', 4)
    #TODO: Change back if there are more modes
    self.step0_layoutSelectionCollapsibleButton.text = "Layout selector"
    # self.step0_layoutSelectionCollapsibleButton.text = "Layout and mode selector"
    self.sliceletPanelLayout.addWidget(self.step0_layoutSelectionCollapsibleButton)
    self.step0_layoutSelectionCollapsibleButtonLayout = qt.QFormLayout(self.step0_layoutSelectionCollapsibleButton)
    self.step0_layoutSelectionCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step0_layoutSelectionCollapsibleButtonLayout.setSpacing(4)
    self.step0_viewSelectorComboBox = qt.QComboBox(self.step0_layoutSelectionCollapsibleButton)
    self.step0_viewSelectorComboBox.addItem("Four-up (3D + 3x2D)")
    self.step0_viewSelectorComboBox.addItem("Conventional (3D + 3x2D)")
    self.step0_viewSelectorComboBox.addItem("3D-only view")
    self.step0_viewSelectorComboBox.addItem("Axial slice only view")
    self.step0_viewSelectorComboBox.addItem("Double 3D view")
    self.step0_viewSelectorComboBox.addItem("Four-up plus plot view")
    self.step0_viewSelectorComboBox.addItem("Plot only view")
    self.step0_layoutSelectionCollapsibleButtonLayout.addRow("Layout: ", self.step0_viewSelectorComboBox)
    self.step0_viewSelectorComboBox.connect('activated(int)', self.onViewSelect)

    # Mode Selector: Radio-buttons
    self.step0_modeSelectorLayout = qt.QGridLayout()
    self.step0_modeSelectorLabel = qt.QLabel('Select mode: ')
    self.step0_modeSelectorLayout.addWidget(self.step0_modeSelectorLabel, 0, 0, 1, 1)
    self.step0_clinicalModeRadioButton = qt.QRadioButton('Clinical MR readout')
    self.step0_clinicalModeRadioButton.setChecked(True)
    self.step0_modeSelectorLayout.addWidget(self.step0_clinicalModeRadioButton, 0, 1)
    self.step0_preclinicalModeRadioButton = qt.QRadioButton('Clinical MR readout')
    self.step0_modeSelectorLayout.addWidget(self.step0_preclinicalModeRadioButton, 0, 2)
    self.step0_clinicalModeRadioButton.connect('toggled(bool)', self.onClinicalModeSelect)
    self.step0_preclinicalModeRadioButton.connect('toggled(bool)', self.onClinicalModeSelect) 

  #------------------------------------------------------------------------------
  def setup_Step1_LoadData(self):
    # Step 1: Load data panel
    self.step1_loadDataCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step1_loadDataCollapsibleButton.text = "1. Load data"
    self.sliceletPanelLayout.addWidget(self.step1_loadDataCollapsibleButton)
    self.step1_loadDataCollapsibleButtonLayout = qt.QFormLayout(self.step1_loadDataCollapsibleButton)
    self.step1_loadDataCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step1_loadDataCollapsibleButtonLayout.setSpacing(4)

    # Load data label
    # 1.1 Load DICOM data
    self.step1_1_dicomCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_1_dicomCollapsibleButton.text = "1.1. Load DICOM data"
    self.step1_1_dicomCollapsibleButton.collapsed = False
    self.step1_loadDataCollapsibleButtonLayout.addRow(self.step1_1_dicomCollapsibleButton)
    self.step1_1_dicomLayout = qt.QFormLayout(self.step1_1_dicomCollapsibleButton)
    self.step1_1_dicomLayout.setContentsMargins(12,4,4,4)
    self.step1_1_dicomLayout.setSpacing(0)

    # Load DICOM data button
    self.step1_showDicomBrowserButton = qt.QPushButton("Load DICOM data")
    self.step1_showDicomBrowserButton.toolTip = "Load planning data (CT or MRI, dose, structures)"
    self.step1_showDicomBrowserButton.name = "showDicomBrowserButton"
    self.step1_1_dicomLayout.addRow(self.step1_showDicomBrowserButton)

    # Assign data label
    self.step1_AssignDataLabel = qt.QLabel("Load and assign all DICOM data involved in the workflow.\nNote: If this selection is changed later then all the following steps need to be performed again")
    self.step1_AssignDataLabel.wordWrap = True
    self.step1_1_dicomLayout.addRow(self.step1_AssignDataLabel)
    # Planning volume node selector
    self.planningSelector = slicer.qMRMLNodeComboBox()
    self.planningSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.planningSelector.addEnabled = False
    self.planningSelector.removeEnabled = False
    self.planningSelector.setMRMLScene(slicer.mrmlScene)
    self.planningSelector.setToolTip("Pick the planning volume")
    self.step1_1_dicomLayout.addRow('Planning volume: ', self.planningSelector)

    # PLANDOSE node selector
    self.planDoseSelector = slicer.qMRMLNodeComboBox()
    self.planDoseSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.planDoseSelector.addEnabled = False
    self.planDoseSelector.removeEnabled = False
    self.planDoseSelector.setMRMLScene(slicer.mrmlScene)
    self.planDoseSelector.setToolTip("Pick the planning dose volume.")
    self.step1_1_dicomLayout.addRow('Plan dose volume: ', self.planDoseSelector)

    # PLANSTRUCTURES node selector
    self.planStructuresSelector = slicer.qMRMLNodeComboBox()
    self.planStructuresSelector.nodeTypes = ["vtkMRMLSegmentationNode"]
    self.planStructuresSelector.addEnabled = False
    self.planStructuresSelector.removeEnabled = False
    self.planStructuresSelector.setMRMLScene(slicer.mrmlScene)
    self.planStructuresSelector.setToolTip("Pick the planning structure set.")
    self.step1_1_dicomLayout.addRow('Structures: ', self.planStructuresSelector)

    # IGRT volume node selector
    self.igrtSelector = slicer.qMRMLNodeComboBox()
    self.igrtSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.igrtSelector.addEnabled = False
    self.igrtSelector.removeEnabled = False
    self.igrtSelector.setMRMLScene(slicer.mrmlScene)
    self.igrtSelector.setToolTip("Pick the IGRT volume.")
    self.step1_1_dicomLayout.addRow('IGRT volume: ', self.igrtSelector)

    # Measured volume selectors: automatically points to ΔR1 or ΔR2 map
    # self.measuredVolumeSelector = slicer.qMRMLNodeComboBox()
    # self.measuredVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    # self.measuredVolumeSelector.addEnabled = False
    # self.measuredVolumeSelector.removeEnabled = False
    # self.measuredVolumeSelector.noneEnabled = True
    # self.measuredVolumeSelector.setMRMLScene(slicer.mrmlScene)

    # # Calibration volume selector
    # self.calibrationVolumeSelector = slicer.qMRMLNodeComboBox()
    # self.calibrationVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    # self.calibrationVolumeSelector.addEnabled = False
    # self.calibrationVolumeSelector.removeEnabled = False
    # self.calibrationVolumeSelector.noneEnabled = True
    # self.calibrationVolumeSelector.setMRMLScene(slicer.mrmlScene)
 
    # 1.2 Load non-DICOM data
    self.step1_2_nonDicomCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_2_nonDicomCollapsibleButton.text = "1.2. Load non-DICOM data"
    self.step1_2_nonDicomCollapsibleButton.collapsed = True  
    self.step1_loadDataCollapsibleButtonLayout.addRow(self.step1_2_nonDicomCollapsibleButton)
    self.step1_2_nonDicomLayout = qt.QFormLayout(self.step1_2_nonDicomCollapsibleButton)
    self.step1_2_nonDicomLayout.setContentsMargins(12,4,4,4)
    self.step1_2_nonDicomLayout.setSpacing(0) 

    # 1.2.1 Load measured gel dosimeter volume
    self.step1_2_1_measuredGelCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_2_1_measuredGelCollapsibleButton.text = "1.2.1. Load measured gel dosimeter volume"
    self.step1_2_1_measuredGelCollapsibleButton.collapsed = True
    self.step1_2_nonDicomLayout.addRow(self.step1_2_1_measuredGelCollapsibleButton)
    self.step1_2_1_measuredGelLayout = qt.QFormLayout(self.step1_2_1_measuredGelCollapsibleButton)
    self.step1_2_1_measuredGelLayout.setContentsMargins(12,4,4,4)
    # self.step1_2_1_measuredGelLayout.setSpacing(4)

    # Load non-DICOM data button
    self.step1_loadNonDicomDataButton = qt.QPushButton("Load non-DICOM data")
    self.step1_loadNonDicomDataButton.toolTip = "Load MR files from NRRD, mha, etc."
    self.step1_loadNonDicomDataButton.name = "loadNonDicomDataButton"
    self.step1_2_1_measuredGelLayout.addRow(self.step1_loadNonDicomDataButton)

    # Pre-irradiation gel volume
    self.step1_2_1_preScanSelector = slicer.qMRMLNodeComboBox()
    self.step1_2_1_preScanSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_2_1_preScanSelector.selectNodeUponCreation = False
    self.step1_2_1_preScanSelector.addEnabled = False
    self.step1_2_1_preScanSelector.removeEnabled = False
    self.step1_2_1_preScanSelector.noneEnabled = True
    self.step1_2_1_preScanSelector.showHidden = False
    self.step1_2_1_preScanSelector.setMRMLScene(slicer.mrmlScene)
    self.step1_2_1_preScanSelector.setToolTip("Select pre-irradiation volume (if available, enables ΔR workflow)")
    self.step1_2_1_measuredGelLayout.addRow("Pre-irradiation volume (optional):", self.step1_2_1_preScanSelector)

    # Post-irradiation gel volume
    self.step1_2_1_postScanSelector = slicer.qMRMLNodeComboBox()
    self.step1_2_1_postScanSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_2_1_postScanSelector.selectNodeUponCreation = False
    self.step1_2_1_postScanSelector.addEnabled = False
    self.step1_2_1_postScanSelector.removeEnabled = False
    self.step1_2_1_postScanSelector.noneEnabled = True
    self.step1_2_1_postScanSelector.showHidden = False
    self.step1_2_1_postScanSelector.setMRMLScene(slicer.mrmlScene)
    self.step1_2_1_postScanSelector.setToolTip("Select post-irradiation volume")
    self.step1_2_1_measuredGelLayout.addRow("Post-irradiation volume:", self.step1_2_1_postScanSelector)

    # 1.2.1.1. Delta R workflow
    self.step1_2_1_1_deltaRLayout = self.step1_2_1_measuredGelLayout

    # 1.2.1.1.2. Registration
    self.step1_2_1_1_step2_registrationButton = ctk.ctkCollapsibleButton()
    self.step1_2_1_1_step2_registrationButton.text = "Register post- to pre-irradiation volume"
    self.step1_2_1_1_step2_registrationButton.collapsed = True
    self.step1_2_1_1_step2_registrationButton.enabled = False
    self.step1_2_1_1_step2_registrationButton.visible = False
    self.step1_2_1_1_deltaRLayout.addRow(self.step1_2_1_1_step2_registrationButton)
    self.step1_2_1_1_step2_registrationLayout = qt.QFormLayout(self.step1_2_1_1_step2_registrationButton)
    self.step1_2_1_1_step2_registrationLayout.setContentsMargins(12,4,4,4)
    
    # Perform Registration button
    self.step1_2_1_1_registerButton = qt.QPushButton("Perform Registration")
    self.step1_2_1_1_registerButton.toolTip = "Automatically register post- to pre-irradiation  volume (takes several seconds)"
    self.step1_2_1_1_step2_registrationLayout.addRow(self.step1_2_1_1_registerButton)

    # Adjust Registration Transform section
    self.step1_2_1_1_adjustTransformLabel = qt.QLabel("If registration result is not satisfactory, a simple re-run of the registration may solve it.")
    self.step1_2_1_1_adjustTransformLabel.setWordWrap(True)
    self.step1_2_1_1_step2_registrationLayout.addRow(self.step1_2_1_1_adjustTransformLabel)

    # Manual transform adjustment section
    self.step1_2_1_1_adjustTransformLabel = qt.QLabel("Adjust transform manually if needed:")
    self.step1_2_1_1_adjustTransformLabel.wordWrap = True
    self.step1_2_1_1_step2_registrationLayout.addRow(self.step1_2_1_1_adjustTransformLabel)
    
    # Translation sliders
    self.step1_2_1_1_translationSliders = slicer.qMRMLTransformSliders()
    translationGroupBox = slicer.util.findChildren(widget=self.step1_2_1_1_translationSliders, className='ctkCollapsibleGroupBox')[0]
    translationGroupBox.collapsed = True
    self.step1_2_1_1_translationSliders.setMRMLScene(slicer.mrmlScene)
    self.step1_2_1_1_step2_registrationLayout.addRow(self.step1_2_1_1_translationSliders)
    
    # Rotation sliders
    self.step1_2_1_1_rotationSliders = slicer.qMRMLTransformSliders()
    self.step1_2_1_1_rotationSliders.minMaxVisible = False
    self.step1_2_1_1_rotationSliders.TypeOfTransform = slicer.qMRMLTransformSliders.ROTATION
    self.step1_2_1_1_rotationSliders.Title = "Rotation"
    self.step1_2_1_1_rotationSliders.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL
    rotationGroupBox = slicer.util.findChildren(widget=self.step1_2_1_1_rotationSliders, className='ctkCollapsibleGroupBox')[0]
    rotationGroupBox.collapsed = True
    self.step1_2_1_1_step2_registrationLayout.addRow(self.step1_2_1_1_rotationSliders)
    
    # Resample button
    self.step1_2_1_1_resampleButton = qt.QPushButton("Resample")
    self.step1_2_1_1_resampleButton.toolTip = "Resample post-irradiation volume with current manual transform adjustments"
    self.step1_2_1_1_resampleButton.enabled = False
    self.step1_2_1_1_resampleButton.visible = False
    self.step1_2_1_1_step2_registrationLayout.addRow(self.step1_2_1_1_resampleButton)

    # GRE checkbox
    self.step1_2_1_1_useGRECheckBox = qt.QCheckBox("GRE images used for registration.")
    self.step1_2_1_1_useGRECheckBox.toolTip = "If checked, apply the registration transform to R1 maps as a separate step"
    self.step1_2_1_1_useGRECheckBox.enabled = False
    self.step1_2_1_1_step2_registrationLayout.addRow(self.step1_2_1_1_useGRECheckBox)

    # Apply transform to R1 maps
    self.step1_2_1_1_applyToR1Button = ctk.ctkCollapsibleButton()
    self.step1_2_1_1_applyToR1Button.text = "Apply transform to R1 map"
    self.step1_2_1_1_applyToR1Button.collapsed = True
    self.step1_2_1_1_applyToR1Button.visible = False
    self.step1_2_1_1_step2_registrationLayout.addRow(self.step1_2_1_1_applyToR1Button)
    self.step1_2_1_1_applyToR1Layout = qt.QFormLayout(self.step1_2_1_1_applyToR1Button)
    self.step1_2_1_1_applyToR1Layout.setContentsMargins(12,4,4,4)

    # R1 pre selector
    self.step1_2_1_1_r1PreSelector = slicer.qMRMLNodeComboBox()
    self.step1_2_1_1_r1PreSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_2_1_1_r1PreSelector.selectNodeUponCreation = False
    self.step1_2_1_1_r1PreSelector.addEnabled = False
    self.step1_2_1_1_r1PreSelector.removeEnabled = False
    self.step1_2_1_1_r1PreSelector.noneEnabled = True
    self.step1_2_1_1_r1PreSelector.showHidden = False
    self.step1_2_1_1_r1PreSelector.setMRMLScene(slicer.mrmlScene)
    self.step1_2_1_1_r1PreSelector.setToolTip("Select pre-irradiation R1 map")
    self.step1_2_1_1_applyToR1Layout.addRow("Pre-irradiation R1 map:", self.step1_2_1_1_r1PreSelector)

    # R1 post selector
    self.step1_2_1_1_r1PostSelector = slicer.qMRMLNodeComboBox()
    self.step1_2_1_1_r1PostSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_2_1_1_r1PostSelector.selectNodeUponCreation = False
    self.step1_2_1_1_r1PostSelector.addEnabled = False
    self.step1_2_1_1_r1PostSelector.removeEnabled = False
    self.step1_2_1_1_r1PostSelector.noneEnabled = True
    self.step1_2_1_1_r1PostSelector.showHidden = False
    self.step1_2_1_1_r1PostSelector.setMRMLScene(slicer.mrmlScene)
    self.step1_2_1_1_r1PostSelector.setToolTip("Select post-irradiation R1 map")
    self.step1_2_1_1_applyToR1Layout.addRow("Post-irradiation R1 map:", self.step1_2_1_1_r1PostSelector)

    # Apply transform button
    self.step1_2_1_1_applyTransformToR1Button = qt.QPushButton("Apply Transform to R1 Maps")
    self.step1_2_1_1_applyTransformToR1Button.toolTip = "Resample R1 post-irradiation volume using the GRE registration transform"
    self.step1_2_1_1_applyToR1Layout.addRow(self.step1_2_1_1_applyTransformToR1Button)

    # 1.2.1.1.3. Denoising
    self.step1_2_1_1_step3_denoisingButton = ctk.ctkCollapsibleButton()
    self.step1_2_1_1_step3_denoisingButton.text = "Denoising (optional)"
    self.step1_2_1_1_step3_denoisingButton.collapsed = True
    self.step1_2_1_1_step3_denoisingButton.enabled = False
    self.step1_2_1_1_step3_denoisingButton.visible = False
    self.step1_2_1_1_deltaRLayout.addRow(self.step1_2_1_1_step3_denoisingButton)
    self.step1_2_1_1_step3_denoisingLayout = qt.QFormLayout(self.step1_2_1_1_step3_denoisingButton)
    self.step1_2_1_1_step3_denoisingLayout.setContentsMargins(12,4,4,4)
    
    # Input image volume
    self.step1_2_1_1_denoisingInputSelector = slicer.qMRMLNodeComboBox()
    self.step1_2_1_1_denoisingInputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_2_1_1_denoisingInputSelector.selectNodeUponCreation = False
    self.step1_2_1_1_denoisingInputSelector.addEnabled = False
    self.step1_2_1_1_denoisingInputSelector.removeEnabled = False
    self.step1_2_1_1_denoisingInputSelector.noneEnabled = False
    self.step1_2_1_1_denoisingInputSelector.showHidden = False
    self.step1_2_1_1_denoisingInputSelector.setMRMLScene(slicer.mrmlScene)
    self.step1_2_1_1_denoisingInputSelector.setToolTip("Select volume to denoise")
    self.step1_2_1_1_step3_denoisingLayout.addRow("Input Image Volume:", self.step1_2_1_1_denoisingInputSelector)

    # Filter type selector - default: Gradient Anisotropic Diffusion
    self.step1_2_1_1_filterTypeComboBox = qt.QComboBox()
    self.step1_2_1_1_filterTypeComboBox.addItem("Gradient Anisotropic Diffusion")
    self.step1_2_1_1_filterTypeComboBox.addItem("Curvature Anisotropic Diffusion")
    self.step1_2_1_1_filterTypeComboBox.addItem("Gaussian Blur Image Filter")
    self.step1_2_1_1_filterTypeComboBox.addItem("Median Image Filter")
    self.step1_2_1_1_filterTypeComboBox.setCurrentIndex(0)  # Default to Gradient Anisotropic Diffusion
    self.step1_2_1_1_filterTypeComboBox.setToolTip("Select denoising filter type")
    self.step1_2_1_1_step3_denoisingLayout.addRow("Filter type:", self.step1_2_1_1_filterTypeComboBox)
    
    # Parameter controls
    # Gradient Anisotropic Diffusion parameters
    self.step1_2_1_1_gradientIterationsSpinBox = qt.QSpinBox() # whole numbers only
    self.step1_2_1_1_gradientIterationsSpinBox.setRange(1, 50)
    self.step1_2_1_1_gradientIterationsSpinBox.setValue(30)
    self.step1_2_1_1_gradientIterationsSpinBox.setToolTip("Number of iterations")

    self.step1_2_1_1_gradientTimeStepSpinBox = qt.QDoubleSpinBox() # decimal numbers
    self.step1_2_1_1_gradientTimeStepSpinBox.setRange(0.001, 0.5)
    self.step1_2_1_1_gradientTimeStepSpinBox.setSingleStep(0.001)
    self.step1_2_1_1_gradientTimeStepSpinBox.setValue(0.02)
    self.step1_2_1_1_gradientTimeStepSpinBox.setToolTip("Time step")

    self.step1_2_1_1_gradientConductanceSpinBox = qt.QDoubleSpinBox()
    self.step1_2_1_1_gradientConductanceSpinBox.setRange(0.1, 10.0)
    self.step1_2_1_1_gradientConductanceSpinBox.setSingleStep(0.1)
    self.step1_2_1_1_gradientConductanceSpinBox.setValue(1.0)
    self.step1_2_1_1_gradientConductanceSpinBox.setToolTip("Conductance parameter")

    # Curvature Anisotropic Diffusion parameters
    self.step1_2_1_1_curvatureIterationsSpinBox = qt.QSpinBox()
    self.step1_2_1_1_curvatureIterationsSpinBox.setRange(1, 50)
    self.step1_2_1_1_curvatureIterationsSpinBox.setValue(30)
    self.step1_2_1_1_curvatureIterationsSpinBox.setToolTip("Number of iterations")

    self.step1_2_1_1_curvatureTimeStepSpinBox = qt.QDoubleSpinBox()
    self.step1_2_1_1_curvatureTimeStepSpinBox.setRange(0.001, 0.5)
    self.step1_2_1_1_curvatureTimeStepSpinBox.setSingleStep(0.001)
    self.step1_2_1_1_curvatureTimeStepSpinBox.setValue(0.02)
    self.step1_2_1_1_curvatureTimeStepSpinBox.setToolTip("Time step")

    self.step1_2_1_1_curvatureConductanceSpinBox = qt.QDoubleSpinBox()
    self.step1_2_1_1_curvatureConductanceSpinBox.setRange(0.1, 10.0)
    self.step1_2_1_1_curvatureConductanceSpinBox.setSingleStep(0.1)
    self.step1_2_1_1_curvatureConductanceSpinBox.setValue(1.0)
    self.step1_2_1_1_curvatureConductanceSpinBox.setToolTip("Conductance parameter")

    # Gaussian Blur Image Filter parameters
    self.step1_2_1_1_gaussianSigmaSpinBox = qt.QDoubleSpinBox()
    self.step1_2_1_1_gaussianSigmaSpinBox.setRange(0.1, 10.0)
    self.step1_2_1_1_gaussianSigmaSpinBox.setSingleStep(0.1)
    self.step1_2_1_1_gaussianSigmaSpinBox.setValue(1.0)
    self.step1_2_1_1_gaussianSigmaSpinBox.setToolTip("Sigma (standard deviation)")

    # Median Image Filter parameters
    self.step1_2_1_1_medianNeighborhoodSpinBox = qt.QSpinBox()
    self.step1_2_1_1_medianNeighborhoodSpinBox.setRange(1, 11)
    self.step1_2_1_1_medianNeighborhoodSpinBox.setSingleStep(2) 
    self.step1_2_1_1_medianNeighborhoodSpinBox.setValue(3)
    self.step1_2_1_1_medianNeighborhoodSpinBox.setToolTip("Neighborhood size (odd number)")

    # Parameter layout
    # Gradient Anisotropic Diffusion parameters
    self.step1_2_1_1_gradientParamsWidget = qt.QWidget()
    gradientLayout = qt.QFormLayout(self.step1_2_1_1_gradientParamsWidget)
    gradientLayout.setContentsMargins(0,0,0,0)
    gradientLayout.addRow("Iterations:", self.step1_2_1_1_gradientIterationsSpinBox)
    gradientLayout.addRow("Time step:", self.step1_2_1_1_gradientTimeStepSpinBox)
    gradientLayout.addRow("Conductance:", self.step1_2_1_1_gradientConductanceSpinBox)
    self.step1_2_1_1_step3_denoisingLayout.addRow(self.step1_2_1_1_gradientParamsWidget)

    # Curvature Anisotropic Diffusion parameter
    self.step1_2_1_1_curvatureParamsWidget = qt.QWidget()
    curvatureLayout = qt.QFormLayout(self.step1_2_1_1_curvatureParamsWidget)
    curvatureLayout.setContentsMargins(0,0,0,0)
    curvatureLayout.addRow("Iterations:", self.step1_2_1_1_curvatureIterationsSpinBox)
    curvatureLayout.addRow("Time step:", self.step1_2_1_1_curvatureTimeStepSpinBox)
    curvatureLayout.addRow("Conductance:", self.step1_2_1_1_curvatureConductanceSpinBox)
    self.step1_2_1_1_step3_denoisingLayout.addRow(self.step1_2_1_1_curvatureParamsWidget)

    # Gaussian Blur Image Filter parameters
    self.step1_2_1_1_gaussianParamsWidget = qt.QWidget()
    gaussianLayout = qt.QFormLayout(self.step1_2_1_1_gaussianParamsWidget)
    gaussianLayout.setContentsMargins(0,0,0,0)
    gaussianLayout.addRow("Sigma:", self.step1_2_1_1_gaussianSigmaSpinBox)
    self.step1_2_1_1_step3_denoisingLayout.addRow(self.step1_2_1_1_gaussianParamsWidget)

    # Median Image Filter parameters
    self.step1_2_1_1_medianParamsWidget = qt.QWidget()
    medianLayout = qt.QFormLayout(self.step1_2_1_1_medianParamsWidget)
    medianLayout.setContentsMargins(0,0,0,0)
    medianLayout.addRow("Kernel size:", self.step1_2_1_1_medianNeighborhoodSpinBox)
    self.step1_2_1_1_step3_denoisingLayout.addRow(self.step1_2_1_1_medianParamsWidget)

    # Apply Denoising button
    self.step1_2_1_1_applyDenoisingButton = qt.QPushButton("Apply Denoising")
    self.step1_2_1_1_applyDenoisingButton.toolTip = "Apply selected denoising filter to volume"
    self.step1_2_1_1_step3_denoisingLayout.addRow(self.step1_2_1_1_applyDenoisingButton)
    self.onFilterTypeChanged(0)

    # 1.2.1.1.4. Compute Delta R
    self.step1_2_1_1_step4_computeButton = ctk.ctkCollapsibleButton()
    self.step1_2_1_1_step4_computeButton.text = "Compute ΔR1 or ΔR2 map"
    self.step1_2_1_1_step4_computeButton.collapsed = True
    self.step1_2_1_1_step4_computeButton.enabled = False
    self.step1_2_1_1_step4_computeButton.visible = False
    self.step1_2_1_1_deltaRLayout.addRow(self.step1_2_1_1_step4_computeButton)
    self.step1_2_1_1_step4_computeLayout = qt.QFormLayout(self.step1_2_1_1_step4_computeButton)
    self.step1_2_1_1_step4_computeLayout.setContentsMargins(12,4,4,4)

    self.step1_2_1_1_computeDeltaRButton = qt.QPushButton("Compute ΔR1 or ΔR2 map")
    self.step1_2_1_1_computeDeltaRButton.toolTip = "Subtract pre- from registered post-irradiation volume"
    self.step1_2_1_1_computeDeltaRButton.enabled = False
    self.step1_2_1_1_step4_computeLayout.addRow(self.step1_2_1_1_computeDeltaRButton)
    self.step1_2_1_1_statusLabel = qt.QLabel("")
    self.step1_2_1_1_statusLabel.setWordWrap(True)
    self.step1_2_1_1_deltaRLayout.addRow(self.step1_2_1_1_statusLabel)
    
    # Make Steps 1-4 mutually exclusive (only one active at a time)
    self.step1_2_1_1_stepsButtonGroup = qt.QButtonGroup()
    self.step1_2_1_1_stepsButtonGroup.addButton(self.step1_2_1_1_step2_registrationButton)
    self.step1_2_1_1_stepsButtonGroup.addButton(self.step1_2_1_1_step3_denoisingButton)
    self.step1_2_1_1_stepsButtonGroup.addButton(self.step1_2_1_1_step4_computeButton)

    # 1.2.2 Load calibration gel dosimeter volume - OPTIONAL
    self.step1_2_2_calibrationGelCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step1_2_2_calibrationGelCollapsibleButton.text = "1.2.2. Load calibration gel dosimeter volume (optional)"
    self.step1_2_2_calibrationGelCollapsibleButton.collapsed = True
    self.step1_2_nonDicomLayout.addRow(self.step1_2_2_calibrationGelCollapsibleButton)
    self.step1_2_2_calibrationGelLayout = qt.QFormLayout(self.step1_2_2_calibrationGelCollapsibleButton)
    self.step1_2_2_calibrationGelLayout.setContentsMargins(12,4,4,4)

    self.step1_2_2_loadNonDicomDataButton = qt.QPushButton("Load non-DICOM data")
    self.step1_2_2_loadNonDicomDataButton.toolTip = "Load calibration gel MR files from NRRD, mha, etc."
    self.step1_2_2_loadNonDicomDataButton.name = "loadCalibrationNonDicomDataButton"
    self.step1_2_2_calibrationGelLayout.addRow(self.step1_2_2_loadNonDicomDataButton)

    # Pre-irradiation calibration gel volume
    self.step1_2_2_preScanSelector = slicer.qMRMLNodeComboBox()
    self.step1_2_2_preScanSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_2_2_preScanSelector.selectNodeUponCreation = False
    self.step1_2_2_preScanSelector.addEnabled = False
    self.step1_2_2_preScanSelector.removeEnabled = False
    self.step1_2_2_preScanSelector.noneEnabled = True
    self.step1_2_2_preScanSelector.showHidden = False
    self.step1_2_2_preScanSelector.setMRMLScene(slicer.mrmlScene)
    self.step1_2_2_preScanSelector.setToolTip("Select pre-irradiation calibration gel volume (if available, enables ΔR workflow)")
    self.step1_2_2_calibrationGelLayout.addRow("Pre-irradiation volume (optional):", self.step1_2_2_preScanSelector)

    # Post-irradiation calibration gel volume
    self.step1_2_2_postScanSelector = slicer.qMRMLNodeComboBox()
    self.step1_2_2_postScanSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_2_2_postScanSelector.selectNodeUponCreation = False
    self.step1_2_2_postScanSelector.addEnabled = False
    self.step1_2_2_postScanSelector.removeEnabled = False
    self.step1_2_2_postScanSelector.noneEnabled = True
    self.step1_2_2_postScanSelector.showHidden = False
    self.step1_2_2_postScanSelector.setMRMLScene(slicer.mrmlScene)
    self.step1_2_2_postScanSelector.setToolTip("Select post-irradiation calibration gel volume")
    self.step1_2_2_calibrationGelLayout.addRow("Post-irradiation volume:", self.step1_2_2_postScanSelector)

    # 1.2.2.1. Delta R workflow section for calibration gel
    self.step1_2_2_1_deltaRLayout = self.step1_2_2_calibrationGelLayout

    # 1.2.2.1.2. Registration for calibration
    self.step1_2_2_1_step2_registrationButton = ctk.ctkCollapsibleButton()
    self.step1_2_2_1_step2_registrationButton.text = "Register post- to pre-irradiation volume"
    self.step1_2_2_1_step2_registrationButton.collapsed = True
    self.step1_2_2_1_step2_registrationButton.enabled = False
    self.step1_2_2_1_step2_registrationButton.visible = False
    self.step1_2_2_1_deltaRLayout.addRow(self.step1_2_2_1_step2_registrationButton)
    self.step1_2_2_1_step2_registrationLayout = qt.QFormLayout(self.step1_2_2_1_step2_registrationButton)
    self.step1_2_2_1_step2_registrationLayout.setContentsMargins(12,4,4,4)
    
    # Perform Registration button
    self.step1_2_2_1_registerButton = qt.QPushButton("Perform Registration")
    self.step1_2_2_1_registerButton.toolTip = "Automatically register post- to pre-irradiation volume (takes several seconds)"
    self.step1_2_2_1_step2_registrationLayout.addRow(self.step1_2_2_1_registerButton)
    
    # Adjust Registration Transform section
    self.step1_2_2_1_adjustTransformLabel = qt.QLabel("If registration result is not satisfactory, a simple re-run of the registration may solve it.")
    self.step1_2_2_1_adjustTransformLabel.setWordWrap(True)
    self.step1_2_2_1_step2_registrationLayout.addRow(self.step1_2_2_1_adjustTransformLabel)
    
    # Manual transform adjustment section
    self.step1_2_2_1_adjustTransformLabel = qt.QLabel("Adjust transform manually if needed:")
    self.step1_2_2_1_adjustTransformLabel.wordWrap = True
    self.step1_2_2_1_step2_registrationLayout.addRow(self.step1_2_2_1_adjustTransformLabel)
    
    # Translation sliders
    self.step1_2_2_1_translationSliders = slicer.qMRMLTransformSliders()
    translationGroupBox = slicer.util.findChildren(widget=self.step1_2_2_1_translationSliders, className='ctkCollapsibleGroupBox')[0]
    translationGroupBox.collapsed = True
    self.step1_2_2_1_translationSliders.setMRMLScene(slicer.mrmlScene)
    self.step1_2_2_1_step2_registrationLayout.addRow(self.step1_2_2_1_translationSliders)
    
    # Rotation sliders
    self.step1_2_2_1_rotationSliders = slicer.qMRMLTransformSliders()
    self.step1_2_2_1_rotationSliders.minMaxVisible = False
    self.step1_2_2_1_rotationSliders.TypeOfTransform = slicer.qMRMLTransformSliders.ROTATION
    self.step1_2_2_1_rotationSliders.Title = "Rotation"
    self.step1_2_2_1_rotationSliders.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL
    rotationGroupBox = slicer.util.findChildren(widget=self.step1_2_2_1_rotationSliders, className='ctkCollapsibleGroupBox')[0]
    rotationGroupBox.collapsed = True
    self.step1_2_2_1_step2_registrationLayout.addRow(self.step1_2_2_1_rotationSliders)

    # Resample button
    self.step1_2_2_1_resampleButton = qt.QPushButton("Resample")
    self.step1_2_2_1_resampleButton.toolTip = "Resample post-irradiation volume with current manual transform adjustments"
    self.step1_2_2_1_resampleButton.enabled = False
    self.step1_2_2_1_resampleButton.visible = False  
    self.step1_2_2_1_step2_registrationLayout.addRow(self.step1_2_2_1_resampleButton)

    # GRE checkbox
    self.step1_2_2_1_useGRECheckBox = qt.QCheckBox("GRE images used for registration.")
    self.step1_2_2_1_useGRECheckBox.toolTip = "If checked, apply the registration transform to R1 maps as a separate step"
    self.step1_2_2_1_useGRECheckBox.enabled = False
    self.step1_2_2_1_step2_registrationLayout.addRow(self.step1_2_2_1_useGRECheckBox)

    # Apply transform to R1 maps
    self.step1_2_2_1_applyToR1Button = ctk.ctkCollapsibleButton()
    self.step1_2_2_1_applyToR1Button.text = "Apply transform to R1 maps"
    self.step1_2_2_1_applyToR1Button.collapsed = True
    self.step1_2_2_1_applyToR1Button.visible = False
    self.step1_2_2_1_step2_registrationLayout.addRow(self.step1_2_2_1_applyToR1Button)
    self.step1_2_2_1_applyToR1Layout = qt.QFormLayout(self.step1_2_2_1_applyToR1Button)
    self.step1_2_2_1_applyToR1Layout.setContentsMargins(12,4,4,4)

    # R1 pre selector
    self.step1_2_2_1_r1PreSelector = slicer.qMRMLNodeComboBox()
    self.step1_2_2_1_r1PreSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_2_2_1_r1PreSelector.selectNodeUponCreation = False
    self.step1_2_2_1_r1PreSelector.addEnabled = False
    self.step1_2_2_1_r1PreSelector.removeEnabled = False
    self.step1_2_2_1_r1PreSelector.noneEnabled = True
    self.step1_2_2_1_r1PreSelector.showHidden = False
    self.step1_2_2_1_r1PreSelector.setMRMLScene(slicer.mrmlScene)
    self.step1_2_2_1_r1PreSelector.setToolTip("Select pre-irradiation R1 map")
    self.step1_2_2_1_applyToR1Layout.addRow("R1 pre-irradiation:", self.step1_2_2_1_r1PreSelector)

    # R1 post selector
    self.step1_2_2_1_r1PostSelector = slicer.qMRMLNodeComboBox()
    self.step1_2_2_1_r1PostSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_2_2_1_r1PostSelector.selectNodeUponCreation = False
    self.step1_2_2_1_r1PostSelector.addEnabled = False
    self.step1_2_2_1_r1PostSelector.removeEnabled = False
    self.step1_2_2_1_r1PostSelector.noneEnabled = True
    self.step1_2_2_1_r1PostSelector.showHidden = False
    self.step1_2_2_1_r1PostSelector.setMRMLScene(slicer.mrmlScene)
    self.step1_2_2_1_r1PostSelector.setToolTip("Select post-irradiation R1 map")
    self.step1_2_2_1_applyToR1Layout.addRow("R1 post-irradiation:", self.step1_2_2_1_r1PostSelector)

    # Apply transform button
    self.step1_2_2_1_applyTransformToR1Button = qt.QPushButton("Apply Transform to R1 Maps")
    self.step1_2_2_1_applyTransformToR1Button.toolTip = "Resample R1 post using the GRE registration transform"
    self.step1_2_2_1_applyToR1Layout.addRow(self.step1_2_2_1_applyTransformToR1Button)

    # 1.2.2.1.3. Denoising for calibration
    self.step1_2_2_1_step3_denoisingButton = ctk.ctkCollapsibleButton()
    self.step1_2_2_1_step3_denoisingButton.text = "Denoising (optional)"
    self.step1_2_2_1_step3_denoisingButton.collapsed = True
    self.step1_2_2_1_step3_denoisingButton.enabled = False
    self.step1_2_2_1_step3_denoisingButton.visible = False
    self.step1_2_2_1_deltaRLayout.addRow(self.step1_2_2_1_step3_denoisingButton)
    self.step1_2_2_1_step3_denoisingLayout = qt.QFormLayout(self.step1_2_2_1_step3_denoisingButton)
    self.step1_2_2_1_step3_denoisingLayout.setContentsMargins(12,4,4,4)

    # Input image volume
    self.step1_2_2_1_denoisingInputSelector = slicer.qMRMLNodeComboBox()
    self.step1_2_2_1_denoisingInputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step1_2_2_1_denoisingInputSelector.selectNodeUponCreation = False
    self.step1_2_2_1_denoisingInputSelector.addEnabled = False
    self.step1_2_2_1_denoisingInputSelector.removeEnabled = False
    self.step1_2_2_1_denoisingInputSelector.noneEnabled = False
    self.step1_2_2_1_denoisingInputSelector.showHidden = False
    self.step1_2_2_1_denoisingInputSelector.setMRMLScene(slicer.mrmlScene)
    self.step1_2_2_1_denoisingInputSelector.setToolTip("Select volume to denoise")
    self.step1_2_2_1_step3_denoisingLayout.addRow("Input Image Volume:", self.step1_2_2_1_denoisingInputSelector)
    
    # Filter type selector - default: Gradient Anisotropic Diffusion
    self.step1_2_2_1_filterTypeComboBox = qt.QComboBox()
    self.step1_2_2_1_filterTypeComboBox.addItem("Gradient Anisotropic Diffusion")
    self.step1_2_2_1_filterTypeComboBox.addItem("Curvature Anisotropic Diffusion")
    self.step1_2_2_1_filterTypeComboBox.addItem("Gaussian Blur Image Filter")
    self.step1_2_2_1_filterTypeComboBox.addItem("Median Image Filter")
    self.step1_2_2_1_filterTypeComboBox.setCurrentIndex(0)
    self.step1_2_2_1_filterTypeComboBox.setToolTip("Select denoising filter type")
    self.step1_2_2_1_step3_denoisingLayout.addRow("Filter type:", self.step1_2_2_1_filterTypeComboBox)

    # Parameter controls
    # Gradient Anisotropic Diffusion parameters
    self.step1_2_2_1_gradientIterationsSpinBox = qt.QSpinBox()
    self.step1_2_2_1_gradientIterationsSpinBox.setRange(1, 50)
    self.step1_2_2_1_gradientIterationsSpinBox.setValue(30)
    self.step1_2_2_1_gradientIterationsSpinBox.setToolTip("Number of iterations")

    self.step1_2_2_1_gradientTimeStepSpinBox = qt.QDoubleSpinBox()
    self.step1_2_2_1_gradientTimeStepSpinBox.setRange(0.001, 0.5)
    self.step1_2_2_1_gradientTimeStepSpinBox.setSingleStep(0.001)
    self.step1_2_2_1_gradientTimeStepSpinBox.setValue(0.0625)
    self.step1_2_2_1_gradientTimeStepSpinBox.setToolTip("Time step")

    self.step1_2_2_1_gradientConductanceSpinBox = qt.QDoubleSpinBox()
    self.step1_2_2_1_gradientConductanceSpinBox.setRange(0.1, 10.0)
    self.step1_2_2_1_gradientConductanceSpinBox.setSingleStep(0.1)
    self.step1_2_2_1_gradientConductanceSpinBox.setValue(1.0)
    self.step1_2_2_1_gradientConductanceSpinBox.setToolTip("Conductance parameter")

    # Curvature Anisotropic Diffusion parameters
    self.step1_2_2_1_curvatureIterationsSpinBox = qt.QSpinBox()
    self.step1_2_2_1_curvatureIterationsSpinBox.setRange(1, 50)
    self.step1_2_2_1_curvatureIterationsSpinBox.setValue(30)
    self.step1_2_2_1_curvatureIterationsSpinBox.setToolTip("Number of iterations")

    self.step1_2_2_1_curvatureTimeStepSpinBox = qt.QDoubleSpinBox()
    self.step1_2_2_1_curvatureTimeStepSpinBox.setRange(0.001, 0.5)
    self.step1_2_2_1_curvatureTimeStepSpinBox.setSingleStep(0.001)
    self.step1_2_2_1_curvatureTimeStepSpinBox.setValue(0.0625)
    self.step1_2_2_1_curvatureTimeStepSpinBox.setToolTip("Time step")

    self.step1_2_2_1_curvatureConductanceSpinBox = qt.QDoubleSpinBox()
    self.step1_2_2_1_curvatureConductanceSpinBox.setRange(0.1, 10.0)
    self.step1_2_2_1_curvatureConductanceSpinBox.setSingleStep(0.1)
    self.step1_2_2_1_curvatureConductanceSpinBox.setValue(1.0)
    self.step1_2_2_1_curvatureConductanceSpinBox.setToolTip("Conductance parameter")

    # Gaussian Blur Image Filter parameters
    self.step1_2_2_1_gaussianSigmaSpinBox = qt.QDoubleSpinBox()
    self.step1_2_2_1_gaussianSigmaSpinBox.setRange(0.1, 10.0)
    self.step1_2_2_1_gaussianSigmaSpinBox.setSingleStep(0.1)
    self.step1_2_2_1_gaussianSigmaSpinBox.setValue(1.0)
    self.step1_2_2_1_gaussianSigmaSpinBox.setToolTip("Sigma (standard deviation)")

    # Median Image Filter parameters
    self.step1_2_2_1_medianNeighborhoodSpinBox = qt.QSpinBox()
    self.step1_2_2_1_medianNeighborhoodSpinBox.setRange(1, 11)
    self.step1_2_2_1_medianNeighborhoodSpinBox.setSingleStep(2)
    self.step1_2_2_1_medianNeighborhoodSpinBox.setValue(3)
    self.step1_2_2_1_medianNeighborhoodSpinBox.setToolTip("Neighborhood size (odd number)")

    # Parameter layout
    # Gradient Anisotropic Diffusion parameters
    self.step1_2_2_1_gradientParamsWidget = qt.QWidget()
    gradientLayout = qt.QFormLayout(self.step1_2_2_1_gradientParamsWidget)
    gradientLayout.setContentsMargins(0,0,0,0)
    gradientLayout.addRow("Iterations:", self.step1_2_2_1_gradientIterationsSpinBox)
    gradientLayout.addRow("Time step:", self.step1_2_2_1_gradientTimeStepSpinBox)
    gradientLayout.addRow("Conductance:", self.step1_2_2_1_gradientConductanceSpinBox)
    self.step1_2_2_1_step3_denoisingLayout.addRow(self.step1_2_2_1_gradientParamsWidget)

    # Curvature Anisotropic Diffusion parameter
    self.step1_2_2_1_curvatureParamsWidget = qt.QWidget()
    curvatureLayout = qt.QFormLayout(self.step1_2_2_1_curvatureParamsWidget)
    curvatureLayout.setContentsMargins(0,0,0,0)
    curvatureLayout.addRow("Iterations:", self.step1_2_2_1_curvatureIterationsSpinBox)
    curvatureLayout.addRow("Time step:", self.step1_2_2_1_curvatureTimeStepSpinBox)
    curvatureLayout.addRow("Conductance:", self.step1_2_2_1_curvatureConductanceSpinBox)
    self.step1_2_2_1_step3_denoisingLayout.addRow(self.step1_2_2_1_curvatureParamsWidget)

    # Gaussian Blur Image Filter parameters
    self.step1_2_2_1_gaussianParamsWidget = qt.QWidget()
    gaussianLayout = qt.QFormLayout(self.step1_2_2_1_gaussianParamsWidget)
    gaussianLayout.setContentsMargins(0,0,0,0)
    gaussianLayout.addRow("Sigma:", self.step1_2_2_1_gaussianSigmaSpinBox)
    self.step1_2_2_1_step3_denoisingLayout.addRow(self.step1_2_2_1_gaussianParamsWidget)

    # Median Image Filter parameters
    self.step1_2_2_1_medianParamsWidget = qt.QWidget()
    medianLayout = qt.QFormLayout(self.step1_2_2_1_medianParamsWidget)
    medianLayout.setContentsMargins(0,0,0,0)
    medianLayout.addRow("Kernel size:", self.step1_2_2_1_medianNeighborhoodSpinBox)
    self.step1_2_2_1_step3_denoisingLayout.addRow(self.step1_2_2_1_medianParamsWidget)

    # Apply Denoising button
    self.step1_2_2_1_applyDenoisingButton = qt.QPushButton("Apply Denoising")
    self.step1_2_2_1_applyDenoisingButton.toolTip = "Apply selected denoising filter to volume"
    self.step1_2_2_1_step3_denoisingLayout.addRow(self.step1_2_2_1_applyDenoisingButton)
    self.onCalibrationFilterTypeChanged(0)

    # 1.2.2.1.4. Compute Delta R for calibration
    self.step1_2_2_1_step4_computeButton = ctk.ctkCollapsibleButton()
    self.step1_2_2_1_step4_computeButton.text = "Compute ΔR1 or ΔR2 map"
    self.step1_2_2_1_step4_computeButton.collapsed = True
    self.step1_2_2_1_step4_computeButton.enabled = False
    self.step1_2_2_1_step4_computeButton.visible = False
    self.step1_2_2_1_deltaRLayout.addRow(self.step1_2_2_1_step4_computeButton)
    self.step1_2_2_1_step4_computeLayout = qt.QFormLayout(self.step1_2_2_1_step4_computeButton)
    self.step1_2_2_1_step4_computeLayout.setContentsMargins(12,4,4,4)
    self.step1_2_2_1_step4_computeLayout.setSpacing(4)
    
    self.step1_2_2_1_computeDeltaRButton = qt.QPushButton("Compute ΔR1 or ΔR2 map")
    self.step1_2_2_1_computeDeltaRButton.toolTip = "Subtract pre- from registered post-irradiation volume"
    self.step1_2_2_1_computeDeltaRButton.enabled = False
    self.step1_2_2_1_step4_computeLayout.addRow(self.step1_2_2_1_computeDeltaRButton)
    self.step1_2_2_1_statusLabel = qt.QLabel("")
    self.step1_2_2_1_statusLabel.setWordWrap(True)
    self.step1_2_2_1_deltaRLayout.addRow(self.step1_2_2_1_statusLabel)
    
    # Make Steps 1-4 mutually exclusive for calibration gel
    self.step1_2_2_1_stepsButtonGroup = qt.QButtonGroup()
    self.step1_2_2_1_stepsButtonGroup.addButton(self.step1_2_2_1_step2_registrationButton)
    self.step1_2_2_1_stepsButtonGroup.addButton(self.step1_2_2_1_step3_denoisingButton)
    self.step1_2_2_1_stepsButtonGroup.addButton(self.step1_2_2_1_step4_computeButton)

    # Make 1.2.1 and 1.2.2 mutually exclusive
    self.step1_2_buttonGroup = qt.QButtonGroup()
    self.step1_2_buttonGroup.addButton(self.step1_2_1_measuredGelCollapsibleButton)
    self.step1_2_buttonGroup.addButton(self.step1_2_2_calibrationGelCollapsibleButton)
    
    # Connections
    self.step1_showDicomBrowserButton.connect('clicked()', self.logic.onDicomLoad)
    self.step1_loadDataCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep1_LoadDataCollapsed)
    self.step1_loadNonDicomDataButton.connect('clicked()', self.onLoadNonDicomData)
    self.step1_2_nonDicomCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep1_2_Collapsed)   
    self.step1_2_1_preScanSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onPreScanSelected)
    self.step1_2_1_postScanSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onPostScanSelected)
    self.step1_2_2_loadNonDicomDataButton.connect('clicked()', self.onLoadNonDicomData)
    self.step1_2_2_preScanSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onCalibrationPreScanSelected)
    self.step1_2_2_postScanSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onCalibrationPostScanSelected)
    self.step1_2_1_1_registerButton.connect('clicked()', self.onRegisterPrePost)
    self.step1_2_1_1_translationSliders.connect('valuesChanged()', self.onManualTransformChanged)
    self.step1_2_1_1_rotationSliders.connect('valuesChanged()', self.onManualTransformChanged)
    self.step1_2_1_1_resampleButton.connect('clicked()', self.onResampleMeasured)
    self.step1_2_1_1_useGRECheckBox.connect('toggled(bool)', self.onUseGREToggled)
    self.step1_2_1_1_applyTransformToR1Button.connect('clicked()', self.onApplyTransformToR1)
    self.step1_2_1_1_step3_denoisingButton.connect('contentsCollapsed(bool)', lambda collapsed: self.onFilterTypeChanged(self.step1_2_1_1_filterTypeComboBox.currentIndex) if not collapsed else None)
    self.step1_2_1_1_filterTypeComboBox.connect('currentIndexChanged(int)', self.onFilterTypeChanged) # Show parameters for that selected filter
    self.step1_2_1_1_applyDenoisingButton.connect('clicked()', self.onApplyDenoising)
    self.step1_2_1_1_computeDeltaRButton.connect('clicked()', self.onComputeDeltaR)
    self.step1_2_2_1_registerButton.connect('clicked()', self.onCalibrationRegisterPrePost)
    self.step1_2_2_1_translationSliders.connect('valuesChanged()', self.onCalibrationManualTransformChanged)
    self.step1_2_2_1_rotationSliders.connect('valuesChanged()', self.onCalibrationManualTransformChanged)
    self.step1_2_2_1_resampleButton.connect('clicked()', self.onResampleCalibration)
    self.step1_2_2_1_useGRECheckBox.connect('toggled(bool)', self.onCalibrationUseGREToggled)
    self.step1_2_2_1_applyTransformToR1Button.connect('clicked()', self.onCalibrationApplyTransformToR1)
    self.step1_2_2_1_step3_denoisingButton.connect('contentsCollapsed(bool)', lambda collapsed: self.onCalibrationFilterTypeChanged(self.step1_2_2_1_filterTypeComboBox.currentIndex) if not collapsed else None)
    self.step1_2_2_1_filterTypeComboBox.connect('currentIndexChanged(int)', self.onCalibrationFilterTypeChanged)
    self.step1_2_2_1_applyDenoisingButton.connect('clicked()', self.onCalibrationApplyDenoising)
    self.step1_2_2_1_computeDeltaRButton.connect('clicked()', self.onCalibrationComputeDeltaR)

    # Make 1.1 and 1.2 mutually exclusive
    self.step1_loadDataButtonGroup = qt.QButtonGroup()
    self.step1_loadDataButtonGroup.addButton(self.step1_1_dicomCollapsibleButton)
    self.step1_loadDataButtonGroup.addButton(self.step1_2_nonDicomCollapsibleButton)
    

  #------------------------------------------------------------------------------
  def setup_Step2_Registration(self):
    # Step 2: Registration step
    self.step2_registrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_registrationCollapsibleButton.text = "2. Registration"
    self.sliceletPanelLayout.addWidget(self.step2_registrationCollapsibleButton)
    self.step2_registrationCollapsibleButtonLayout = qt.QFormLayout(self.step2_registrationCollapsibleButton)
    self.step2_registrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step2_registrationCollapsibleButtonLayout.setSpacing(4)

    # ------------------------------------------
    # Step 2.1: IGRT volume to planning volume registration panel
    self.step2_1_planningToIGRTRegistrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_1_planningToIGRTRegistrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_1_planningToIGRTRegistrationCollapsibleButton.text = "2.1. Register planning volume to IGRT volume"
    self.step2_registrationCollapsibleButtonLayout.addWidget(self.step2_1_planningToIGRTRegistrationCollapsibleButton)
    self.step2_1_planningToIGRTRegistrationLayout = qt.QVBoxLayout(self.step2_1_planningToIGRTRegistrationCollapsibleButton)
    self.step2_1_planningToIGRTRegistrationLayout.setContentsMargins(12,4,4,4)
    self.step2_1_planningToIGRTRegistrationLayout.setSpacing(0)

    # Radio button for selecting registration type
    self.step2_1_registrationTypeLayout = qt.QHBoxLayout(self.step2_1_planningToIGRTRegistrationCollapsibleButton)
    self.step2_1_registrationTypeLabel = qt.QLabel('Registration type:')
    self.step2_1_registrationTypeAutomaticRadioButton = qt.QRadioButton('Automatic image-based')
    self.step2_1_registrationTypeLandmarkRadioButton = qt.QRadioButton('Landmark-based')
    self.step2_1_registrationTypeLayout.addWidget(self.step2_1_registrationTypeLabel)
    self.step2_1_registrationTypeLayout.addWidget(self.step2_1_registrationTypeAutomaticRadioButton)
    self.step2_1_registrationTypeLayout.addWidget(self.step2_1_registrationTypeLandmarkRadioButton)
    self.step2_1_planningToIGRTRegistrationLayout.addLayout(self.step2_1_registrationTypeLayout)

    # Add empty row
    self.step2_1_planningToIGRTRegistrationLayout.addWidget(qt.QLabel(' '))

    #
    # Automatic IGRT volume to planning volume registration
    #
    self.step2_1_planningToIGRTRegistrationFrame = qt.QFrame(self.step2_1_planningToIGRTRegistrationCollapsibleButton)
    self.step2_1_planningToIGRTRegistrationFrameLayout = qt.QFormLayout(self.step2_1_planningToIGRTRegistrationFrame)
    self.step2_1_planningToIGRTRegistrationFrameLayout.setContentsMargins(0,0,0,0)
    self.step2_1_planningToIGRTRegistrationFrameLayout.setSpacing(4)

    # Registration label
    self.step2_1_registrationLabel = qt.QLabel("Automatically register the planning volume to the IGRT volume.\nIt should take several seconds.")
    self.step2_1_registrationLabel.wordWrap = True
    self.step2_1_planningToIGRTRegistrationFrameLayout.addRow(self.step2_1_registrationLabel)

    # IGRT volume to planning volume registration button
    self.step2_1_registerPlanningToIGRTButton = qt.QPushButton("Perform registration")
    self.step2_1_registerPlanningToIGRTButton.toolTip = "Register planning volume to IGRT volume"
    self.step2_1_registerPlanningToIGRTButton.name = "step2_1_registerPlanningToIGRTButton"
    self.step2_1_planningToIGRTRegistrationFrameLayout.addRow(self.step2_1_registerPlanningToIGRTButton)

    # Add empty row
    self.step2_1_planningToIGRTRegistrationFrameLayout.addRow(' ', None)

    # Transform fine-tune controls
    self.step2_1_transformSlidersInfoLabel = qt.QLabel("If registration result is not satisfactory, a simple re-run of the registration may solve it.\nOtherwise adjust result registration transform if needed:")
    self.step2_1_transformSlidersInfoLabel.wordWrap = True
    self.step2_1_translationSliders = slicer.qMRMLTransformSliders()
    #self.step2_1_translationSliders.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL # This would make the sliders always start form 0 (then min/max would also not be needed)
    translationGroupBox = slicer.util.findChildren(widget=self.step2_1_translationSliders, className='ctkCollapsibleGroupBox')[0]
    translationGroupBox.collapsed  = True # Collapse by default
    self.step2_1_translationSliders.setMRMLScene(slicer.mrmlScene)
    self.step2_1_rotationSliders = slicer.qMRMLTransformSliders()
    self.step2_1_rotationSliders.minMaxVisible = False
    self.step2_1_rotationSliders.TypeOfTransform = slicer.qMRMLTransformSliders.ROTATION
    self.step2_1_rotationSliders.Title = "Rotation"
    self.step2_1_rotationSliders.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL
    rotationGroupBox = slicer.util.findChildren(widget=self.step2_1_rotationSliders, className='ctkCollapsibleGroupBox')[0]
    rotationGroupBox.collapsed  = True # Collapse by default
    # self.step2_1_rotationSliders.setMRMLScene(slicer.mrmlScene) # If scene is set, then mm appears instead of degrees
    self.step2_1_planningToIGRTRegistrationFrameLayout.addRow(self.step2_1_transformSlidersInfoLabel)
    self.step2_1_planningToIGRTRegistrationFrameLayout.addRow(self.step2_1_translationSliders)
    self.step2_1_planningToIGRTRegistrationFrameLayout.addRow(self.step2_1_rotationSliders)

    self.step2_1_planningToIGRTRegistrationLayout.addWidget(self.step2_1_planningToIGRTRegistrationFrame)

    #
    # Landmark IGRT volume to planning volume registration
    #
    self.step2_1_landmarkPlanningToIGRTRegistrationFrame = qt.QFrame(self.step2_1_planningToIGRTRegistrationCollapsibleButton)
    self.step2_1_landmarkPlanningToIGRTRegistrationFrameLayout = qt.QFormLayout(self.step2_1_landmarkPlanningToIGRTRegistrationFrame)
    self.step2_1_landmarkPlanningToIGRTRegistrationFrameLayout.setContentsMargins(0,0,0,0)
    self.step2_1_landmarkPlanningToIGRTRegistrationFrameLayout.setSpacing(4)

    # Step 2.1.1: Select IGRT fiducials on IGRT volume
    self.step2_1_1_igrtFiducialSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_1_1_igrtFiducialSelectionCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_1_1_igrtFiducialSelectionCollapsibleButton.text = "2.1.1 Select IGRT fiducial points"
    self.step2_1_landmarkPlanningToIGRTRegistrationFrameLayout.addWidget(self.step2_1_1_igrtFiducialSelectionCollapsibleButton)
    self.step2_1_1_igrtFiducialSelectionLayout = qt.QFormLayout(self.step2_1_1_igrtFiducialSelectionCollapsibleButton)
    self.step2_1_1_igrtFiducialSelectionLayout.setContentsMargins(12,4,4,4)
    self.step2_1_1_igrtFiducialSelectionLayout.setSpacing(4)

    # Create instructions label
    self.step2_1_1_instructionsLayout = qt.QHBoxLayout(self.step2_1_1_igrtFiducialSelectionCollapsibleButton)
    self.step2_1_1_igrtFiducialSelectionInfoLabel = qt.QLabel("Locate image plane of the IGRT fiducials, then click the 'Place fiducials' button (blue arrow with red dot). Next, select the fiducial points in the displayed image plane.")
    self.step2_1_1_igrtFiducialSelectionInfoLabel.wordWrap = True
    self.step2_1_1_helpLabel = qt.QLabel()
    self.step2_1_1_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step2_1_1_helpLabel.maximumWidth = 24
    self.step2_1_1_helpLabel.toolTip = "Hint: Use Shift key for '3D cursor' navigation."
    self.step2_1_1_instructionsLayout.addWidget(self.step2_1_1_igrtFiducialSelectionInfoLabel)
    self.step2_1_1_instructionsLayout.addWidget(self.step2_1_1_helpLabel)
    self.step2_1_1_igrtFiducialSelectionLayout.addRow(self.step2_1_1_instructionsLayout)

    # IGRT fiducial selector simple markups widget
    self.step2_1_1_igrtFiducialList = slicer.qSlicerSimpleMarkupsWidget()
    self.step2_1_1_igrtFiducialList.setMRMLScene(slicer.mrmlScene)
    self.step2_1_1_igrtFiducialSelectionLayout.addRow(self.step2_1_1_igrtFiducialList)

    # Step 2.1.2: Select planning fiducials on planning volume
    self.step2_1_2_planningFiducialSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_1_2_planningFiducialSelectionCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_1_2_planningFiducialSelectionCollapsibleButton.text = "2.1.2 Select planning fiducial points"
    self.step2_1_landmarkPlanningToIGRTRegistrationFrameLayout.addWidget(self.step2_1_2_planningFiducialSelectionCollapsibleButton)
    self.step2_1_2_planningFiducialSelectionLayout = qt.QFormLayout(self.step2_1_2_planningFiducialSelectionCollapsibleButton)
    self.step2_1_2_planningFiducialSelectionLayout.setContentsMargins(12,4,4,4)
    self.step2_1_2_planningFiducialSelectionLayout.setSpacing(4)

    # Create instructions label
    self.step2_1_2_instructionsLayout = qt.QHBoxLayout(self.step2_1_2_planningFiducialSelectionCollapsibleButton)
    self.step2_1_2_planningFiducialSelectionInfoLabel = qt.QLabel("Select the fiducial points in the planning volume in the same order as the IGRT fiducials were selected.")
    self.step2_1_2_planningFiducialSelectionInfoLabel.wordWrap = True
    self.step2_1_2_helpLabel = qt.QLabel()
    self.step2_1_2_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step2_1_2_helpLabel.maximumWidth = 24
    self.step2_1_2_helpLabel.toolTip = "Hint: Use Shift key for '3D cursor' navigation.\nHint: If gel dosimeter volume is too dark or low contrast, press left mouse button on the image and drag it to change window/level"
    self.step2_1_2_instructionsLayout.addWidget(self.step2_1_2_planningFiducialSelectionInfoLabel)
    self.step2_1_2_instructionsLayout.addWidget(self.step2_1_2_helpLabel)
    self.step2_1_2_planningFiducialSelectionLayout.addRow(self.step2_1_2_instructionsLayout)

    # Measured fiducial selector simple markups widget
    self.step2_1_2_planningFiducialList = slicer.qSlicerSimpleMarkupsWidget()
    self.step2_1_2_planningFiducialList.setMRMLScene(slicer.mrmlScene)
    self.step2_1_2_planningFiducialSelectionLayout.addRow(self.step2_1_2_planningFiducialList)

    # Step 2.1.3: Perform registration
    self.step2_1_3_planningToIGRTRegistrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_1_3_planningToIGRTRegistrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_1_3_planningToIGRTRegistrationCollapsibleButton.text = "2.1.3 Perform registration"
    self.step2_1_3_planningToIGRTRegistrationCollapsibleButtonLayout = qt.QFormLayout(self.step2_1_3_planningToIGRTRegistrationCollapsibleButton)
    self.step2_1_3_planningToIGRTRegistrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step2_1_3_planningToIGRTRegistrationCollapsibleButtonLayout.setSpacing(4)
    self.step2_1_landmarkPlanningToIGRTRegistrationFrameLayout.addWidget(self.step2_1_3_planningToIGRTRegistrationCollapsibleButton)

    # Registration button - register planning volume to IGRT volume with fiducial registration
    self.step2_1_3_registerPlanningToIGRTButton = qt.QPushButton("Register planning volume to IGRT volume")
    self.step2_1_3_registerPlanningToIGRTButton.toolTip = "Perform fiducial registration between planning volume and IGRT volume"
    self.step2_1_3_registerPlanningToIGRTButton.name = "registerPlanningToIGRTButton"
    self.step2_1_3_planningToIGRTRegistrationCollapsibleButtonLayout.addRow(self.step2_1_3_registerPlanningToIGRTButton)

    # Fiducial error label
    self.step2_1_3_planningToIGRTFiducialRegistrationErrorLabel = qt.QLabel('[Not yet performed]')
    self.step2_1_3_planningToIGRTRegistrationCollapsibleButtonLayout.addRow('Fiducial registration error: ', self.step2_1_3_planningToIGRTFiducialRegistrationErrorLabel)

    # Add empty row
    self.step2_1_3_planningToIGRTRegistrationCollapsibleButtonLayout.addRow(' ', None)

    # Note label about fiducial error
    self.step2_1_3_NoteLabel = qt.QLabel("Note: Typical registration error is < 3mm")
    self.step2_1_3_planningToIGRTRegistrationCollapsibleButtonLayout.addRow(self.step2_1_3_NoteLabel)

    # Add substeps in button groups
    self.step2_1_planningToIGRTRegistrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step2_1_planningToIGRTRegistrationCollapsibleButtonGroup.addButton(self.step2_1_1_igrtFiducialSelectionCollapsibleButton)
    self.step2_1_planningToIGRTRegistrationCollapsibleButtonGroup.addButton(self.step2_1_2_planningFiducialSelectionCollapsibleButton)
    self.step2_1_planningToIGRTRegistrationCollapsibleButtonGroup.addButton(self.step2_1_3_planningToIGRTRegistrationCollapsibleButton)

    self.step2_1_planningToIGRTRegistrationLayout.addWidget(self.step2_1_landmarkPlanningToIGRTRegistrationFrame)

    # Automatic registration by default
    self.step2_1_registrationTypeAutomaticRadioButton.setChecked(True)
    self.step2_1_landmarkPlanningToIGRTRegistrationFrame.setVisible(False)

    # --------------------------------------------------------
    # Step 2.2: Measured gel volume to IGRT volume registration panel
    self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton.text = "2.2. Register gel dosimeter volume to IGRT volume"
    self.step2_registrationCollapsibleButtonLayout.addWidget(self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton)
    self.step2_2_measuredDoseToIgrtRegistrationLayout = qt.QVBoxLayout(self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton)
    self.step2_2_measuredDoseToIgrtRegistrationLayout.setContentsMargins(12,4,4,4)
    self.step2_2_measuredDoseToIgrtRegistrationLayout.setSpacing(0)

    # Radio button for selecting registration type
    self.step2_2_registrationTypeLayout = qt.QHBoxLayout()
    self.step2_2_registrationTypeLabel = qt.QLabel('Registration type:')
    self.step2_2_registrationTypeAutomaticRadioButton = qt.QRadioButton('Automatic image-based')
    self.step2_2_registrationTypeLandmarkRadioButton = qt.QRadioButton('Landmark-based')
    self.step2_2_registrationTypeLayout.addWidget(self.step2_2_registrationTypeLabel)
    self.step2_2_registrationTypeLayout.addWidget(self.step2_2_registrationTypeLandmarkRadioButton)
    self.step2_2_registrationTypeLayout.addWidget(self.step2_2_registrationTypeAutomaticRadioButton)
    self.step2_2_measuredDoseToIgrtRegistrationLayout.addLayout(self.step2_2_registrationTypeLayout)
    self.step2_2_measuredDoseToIgrtRegistrationLayout.addWidget(qt.QLabel(' '))

    # Automatic gel volume to IGRT volume
    self.step2_2_automaticMeasuredToIgrtRegistrationFrame = qt.QFrame(self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton)
    self.step2_2_automaticMeasuredToIgrtRegistrationFrameLayout = qt.QFormLayout(self.step2_2_automaticMeasuredToIgrtRegistrationFrame)
    self.step2_2_automaticMeasuredToIgrtRegistrationFrameLayout.setContentsMargins(0,0,0,0)
    self.step2_2_automaticMeasuredToIgrtRegistrationFrameLayout.setSpacing(4)

    # Registration label
    self.step2_2_automaticRegistrationLabel = qt.QLabel("Automatically register the gel dosimeter volume to the IGRT volume.\nIt should take several seconds.")
    self.step2_2_automaticRegistrationLabel.wordWrap = True
    self.step2_2_automaticMeasuredToIgrtRegistrationFrameLayout.addRow(self.step2_2_automaticRegistrationLabel)

    # Gel volume to IGRT volume registration button
    self.step2_2_registerMeasuredToIgrtAutomaticButton = qt.QPushButton("Perform registration")
    self.step2_2_registerMeasuredToIgrtAutomaticButton.toolTip = "Automatically register gel dosimeter volume to IGRT volume"
    self.step2_2_registerMeasuredToIgrtAutomaticButton.name = "step2_2_registerMeasuredToIgrtAutomaticButton"
    self.step2_2_automaticMeasuredToIgrtRegistrationFrameLayout.addRow(self.step2_2_registerMeasuredToIgrtAutomaticButton)
    self.step2_2_automaticMeasuredToIgrtRegistrationFrameLayout.addRow(' ', None)

    # Transform fine-tune controls
    self.step2_2_transformSlidersInfoLabel = qt.QLabel("If registration result is not satisfactory, a simple re-run of the registration may solve it.\nOtherwise adjust result registration transform if needed:")
    self.step2_2_transformSlidersInfoLabel.wordWrap = True
    self.step2_2_translationSliders = slicer.qMRMLTransformSliders()
    translationGroupBox22 = slicer.util.findChildren(widget=self.step2_2_translationSliders, className='ctkCollapsibleGroupBox')[0]
    translationGroupBox22.collapsed = True
    self.step2_2_translationSliders.setMRMLScene(slicer.mrmlScene)
    self.step2_2_rotationSliders = slicer.qMRMLTransformSliders()
    self.step2_2_rotationSliders.minMaxVisible = False
    self.step2_2_rotationSliders.TypeOfTransform = slicer.qMRMLTransformSliders.ROTATION
    self.step2_2_rotationSliders.Title = "Rotation"
    self.step2_2_rotationSliders.CoordinateReference = slicer.qMRMLTransformSliders.LOCAL
    rotationGroupBox22 = slicer.util.findChildren(widget=self.step2_2_rotationSliders, className='ctkCollapsibleGroupBox')[0]
    rotationGroupBox22.collapsed = True

    self.step2_2_automaticMeasuredToIgrtRegistrationFrameLayout.addRow(self.step2_2_transformSlidersInfoLabel)
    self.step2_2_automaticMeasuredToIgrtRegistrationFrameLayout.addRow(self.step2_2_translationSliders)
    self.step2_2_automaticMeasuredToIgrtRegistrationFrameLayout.addRow(self.step2_2_rotationSliders)

    self.step2_2_measuredDoseToIgrtRegistrationLayout.addWidget(self.step2_2_automaticMeasuredToIgrtRegistrationFrame)

    # Landmark gel volume to IGRT volume
    self.step2_2_landmarkMeasuredToIgrtRegistrationFrame = qt.QFrame(self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton)
    self.step2_2_landmarkMeasuredToIgrtRegistrationFrameLayout = qt.QFormLayout(self.step2_2_landmarkMeasuredToIgrtRegistrationFrame)
    self.step2_2_landmarkMeasuredToIgrtRegistrationFrameLayout.setContentsMargins(0,0,0,0)
    self.step2_2_landmarkMeasuredToIgrtRegistrationFrameLayout.setSpacing(4)

    # Step 2.2.1: Select IGRT fiducials on IGRT volume
    self.step2_2_1_igrtFiducialSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_2_1_igrtFiducialSelectionCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_2_1_igrtFiducialSelectionCollapsibleButton.text = "2.2.1 Select IGRT fiducial points"
    self.step2_2_landmarkMeasuredToIgrtRegistrationFrameLayout.addWidget(self.step2_2_1_igrtFiducialSelectionCollapsibleButton)
    self.step2_2_1_igrtFiducialSelectionLayout = qt.QFormLayout(self.step2_2_1_igrtFiducialSelectionCollapsibleButton)
    self.step2_2_1_igrtFiducialSelectionLayout.setContentsMargins(12,4,4,4)
    self.step2_2_1_igrtFiducialSelectionLayout.setSpacing(4)

    # Create instructions label
    self.step2_2_1_instructionsLayout = qt.QHBoxLayout(self.step2_2_1_igrtFiducialSelectionCollapsibleButton)
    self.step2_2_1_igrtFiducialSelectionInfoLabel = qt.QLabel("Locate image plane of the IGRT fiducials, then click the 'Place fiducials' button (blue arrow with red dot). Next, select the fiducial points in the displayed image plane.")
    self.step2_2_1_igrtFiducialSelectionInfoLabel.wordWrap = True
    self.step2_2_1_helpLabel = qt.QLabel()
    self.step2_2_1_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step2_2_1_helpLabel.maximumWidth = 24
    self.step2_2_1_helpLabel.toolTip = "Hint: Use Shift key for '3D cursor' navigation."
    self.step2_2_1_instructionsLayout.addWidget(self.step2_2_1_igrtFiducialSelectionInfoLabel)
    self.step2_2_1_instructionsLayout.addWidget(self.step2_2_1_helpLabel)
    self.step2_2_1_igrtFiducialSelectionLayout.addRow(self.step2_2_1_instructionsLayout)

    # IGRT fiducial selector simple markups widget
    self.step2_2_1_igrtFiducialList = slicer.qSlicerSimpleMarkupsWidget()
    self.step2_2_1_igrtFiducialList.setMRMLScene(slicer.mrmlScene)
    self.step2_2_1_igrtFiducialSelectionLayout.addRow(self.step2_2_1_igrtFiducialList)

    # Step 2.2.2: Select MEASURED fiducials on MEASURED dose volume
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton.text = "2.2.2 Select measured gel dosimeter fiducial points"
    self.step2_2_landmarkMeasuredToIgrtRegistrationFrameLayout.addWidget(self.step2_2_2_measuredFiducialSelectionCollapsibleButton)
    self.step2_2_2_measuredFiducialSelectionLayout = qt.QFormLayout(self.step2_2_2_measuredFiducialSelectionCollapsibleButton)
    self.step2_2_2_measuredFiducialSelectionLayout.setContentsMargins(12,4,4,4)
    self.step2_2_2_measuredFiducialSelectionLayout.setSpacing(4)

    # Create instructions label
    self.step2_2_2_instructionsLayout = qt.QHBoxLayout(self.step2_2_2_measuredFiducialSelectionCollapsibleButton)
    self.step2_2_2_measuredFiducialSelectionInfoLabel = qt.QLabel("Select the fiducial points in the gel dosimeter volume in the same order as the IGRT fiducials were selected.")
    self.step2_2_2_measuredFiducialSelectionInfoLabel.wordWrap = True
    self.step2_2_2_helpLabel = qt.QLabel()
    self.step2_2_2_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step2_2_2_helpLabel.maximumWidth = 24
    self.step2_2_2_helpLabel.toolTip = "Hint: Use Shift key for '3D cursor' navigation.\nHint: If gel dosimeter volume is too dark or low contrast, press left mouse button on the image and drag it to change window/level"
    self.step2_2_2_instructionsLayout.addWidget(self.step2_2_2_measuredFiducialSelectionInfoLabel)
    self.step2_2_2_instructionsLayout.addWidget(self.step2_2_2_helpLabel)
    self.step2_2_2_measuredFiducialSelectionLayout.addRow(self.step2_2_2_instructionsLayout)

    # Add volume selector for fiducial placement background
    self.step2_2_2_backgroundVolumeSelector = slicer.qMRMLNodeComboBox()
    self.step2_2_2_backgroundVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step2_2_2_backgroundVolumeSelector.selectNodeUponCreation = False
    self.step2_2_2_backgroundVolumeSelector.noneEnabled = False
    self.step2_2_2_backgroundVolumeSelector.setMRMLScene(slicer.mrmlScene)
    self.step2_2_2_backgroundVolumeSelector.toolTip = "Select volume to display during fiducial placement"
    self.step2_2_2_measuredFiducialSelectionLayout.addRow("Display volume:", self.step2_2_2_backgroundVolumeSelector)
    self.step2_2_2_backgroundVolumeSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onMeasuredFiducialBackgroundVolumeChanged)

    # Measured fiducial selector simple markups widget
    self.step2_2_2_measuredFiducialList = slicer.qSlicerSimpleMarkupsWidget()
    self.step2_2_2_measuredFiducialList.setMRMLScene(slicer.mrmlScene)
    self.step2_2_2_measuredFiducialSelectionLayout.addRow(self.step2_2_2_measuredFiducialList)

    # Step 2.2.3: Perform registration
    self.step2_2_3_measuredToIgrtRegistrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step2_2_3_measuredToIgrtRegistrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step2_2_3_measuredToIgrtRegistrationCollapsibleButton.text = "2.2.3 Perform registration"
    self.step2_2_3_measuredToIgrtRegistrationCollapsibleButtonLayout = qt.QFormLayout(self.step2_2_3_measuredToIgrtRegistrationCollapsibleButton)
    self.step2_2_3_measuredToIgrtRegistrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step2_2_3_measuredToIgrtRegistrationCollapsibleButtonLayout.setSpacing(4)
    self.step2_2_landmarkMeasuredToIgrtRegistrationFrameLayout.addWidget(self.step2_2_3_measuredToIgrtRegistrationCollapsibleButton)

    # Registration button - register MEASURED to IGRT volume with fiducial registration
    self.step2_2_3_registerMeasuredToIgrtButton = qt.QPushButton("Register gel volume to IGRT volume")
    self.step2_2_3_registerMeasuredToIgrtButton.toolTip = "Perform fiducial registration between measured gel dosimeter volume and IGRT volume"
    self.step2_2_3_registerMeasuredToIgrtButton.name = "registerMeasuredToIgrtButton"
    self.step2_2_3_measuredToIgrtRegistrationCollapsibleButtonLayout.addRow(self.step2_2_3_registerMeasuredToIgrtButton)

    # Fiducial error label
    self.step2_2_3_measuredToIgrtFiducialRegistrationErrorLabel = qt.QLabel('[Not yet performed]')
    self.step2_2_3_measuredToIgrtRegistrationCollapsibleButtonLayout.addRow('Fiducial registration error: ', self.step2_2_3_measuredToIgrtFiducialRegistrationErrorLabel)

    # Add empty row
    self.step2_2_3_measuredToIgrtRegistrationCollapsibleButtonLayout.addRow(' ', None)

    # Note label about fiducial error
    self.step2_2_3_NoteLabel = qt.QLabel("Note: Typical registration error is < 3mm")
    self.step2_2_3_measuredToIgrtRegistrationCollapsibleButtonLayout.addRow(self.step2_2_3_NoteLabel)

    # Add substeps in button groups
    self.step2_2_registrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step2_2_registrationCollapsibleButtonGroup.addButton(self.step2_1_planningToIGRTRegistrationCollapsibleButton)
    self.step2_2_registrationCollapsibleButtonGroup.addButton(self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton)

    self.step2_2_measuredToIgrtRegistrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step2_2_measuredToIgrtRegistrationCollapsibleButtonGroup.addButton(self.step2_2_1_igrtFiducialSelectionCollapsibleButton)
    self.step2_2_measuredToIgrtRegistrationCollapsibleButtonGroup.addButton(self.step2_2_2_measuredFiducialSelectionCollapsibleButton)
    self.step2_2_measuredToIgrtRegistrationCollapsibleButtonGroup.addButton(self.step2_2_3_measuredToIgrtRegistrationCollapsibleButton)

    self.step2_2_measuredDoseToIgrtRegistrationLayout.addWidget(self.step2_2_landmarkMeasuredToIgrtRegistrationFrame)

    # Landmark registration by default
    self.step2_2_registrationTypeLandmarkRadioButton.setChecked(True)
    self.step2_2_automaticMeasuredToIgrtRegistrationFrame.setVisible(False)

    # Make sure first panels appear when steps are first opened (done before connections to avoid
    # executing those steps, which are only needed when actually switching there during the workflow)
    self.step2_1_1_igrtFiducialSelectionCollapsibleButton.setProperty('collapsed', False)
    self.step2_2_1_igrtFiducialSelectionCollapsibleButton.setProperty('collapsed', False)
    self.step2_1_planningToIGRTRegistrationCollapsibleButton.setProperty('collapsed', False)

    # Connections
    self.step2_registrationCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_RegistrationCollapsed)
    self.step2_1_registrationTypeAutomaticRadioButton.connect('toggled(bool)', self.onAutomaticPlanningToIGRTRegistrationToggled)
    self.step2_1_registerPlanningToIGRTButton.connect('clicked()', self.onPlanningToIGRTAutomaticRegistration)
    self.step2_1_translationSliders.connect('valuesChanged()', self.step2_1_rotationSliders.resetUnactiveSliders)
    self.step2_1_planningToIGRTRegistrationCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_1_PlanningToIGRTRegistrationSelected)
    self.step2_1_1_igrtFiducialSelectionCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_1_1_IGRTFiducialCollectionSelected)
    self.step2_1_2_planningFiducialSelectionCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_1_2_PlanningFiducialCollectionSelected)
    self.step2_1_3_registerPlanningToIGRTButton.connect('clicked()', self.onPlanningToIGRTLandmarkRegistration)
    self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_2_MeasuredDoseToIGRTRegistrationSelected)
    self.step2_2_registrationTypeAutomaticRadioButton.connect('toggled(bool)', self.onAutomaticMeasuredToIgrtRegistrationToggled)
    self.step2_2_registerMeasuredToIgrtAutomaticButton.connect('clicked()', self.onMeasuredToIgrtAutomaticRegistration)
    self.step2_2_translationSliders.connect('valuesChanged()', self.step2_2_rotationSliders.resetUnactiveSliders)
    self.step2_2_1_igrtFiducialSelectionCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_2_1_IGRTFiducialCollectionSelected)
    self.step2_2_2_measuredFiducialSelectionCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep2_2_2_MeasuredFiducialCollectionSelected)
    self.step2_2_3_registerMeasuredToIgrtButton.connect('clicked()', self.onMeasuredToIgrtRegistration)

  #------------------------------------------------------------------------------
  def setup_step3_DoseCalibration(self):
    # Step 3: Calibration step
    self.step3_doseCalibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step3_doseCalibrationCollapsibleButton.text = "3. Dose calibration"
    self.sliceletPanelLayout.addWidget(self.step3_doseCalibrationCollapsibleButton)
    self.step3_doseCalibrationCollapsibleButtonLayout = qt.QVBoxLayout(self.step3_doseCalibrationCollapsibleButton)
    self.step3_doseCalibrationCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step3_doseCalibrationCollapsibleButtonLayout.setSpacing(4)

    # Step 3.1: Calibration routine (optional)
    self.step3_1_calibrationRoutineCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step3_1_calibrationRoutineCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step3_1_calibrationRoutineCollapsibleButton.text = "3.1. Perform calibration routine (optional)"
    self.step3_doseCalibrationCollapsibleButtonLayout.addWidget(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_1_calibrationRoutineLayout = qt.QFormLayout(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_1_calibrationRoutineLayout.setContentsMargins(12,4,4,4)
    self.step3_1_calibrationRoutineLayout.setSpacing(4)

    # Info label
    self.step3_1_calibrationRoutineLayout.addRow(qt.QLabel('Hint: Skip this step if calibration function is already available'))

    # Load Pdd data
    self.step3_1_pddLoadDataButton = qt.QPushButton("Load reference percent depth dose (PDD) data from CSV file")
    self.step3_1_pddLoadDataButton.toolTip = "Load PDD data file from CSV"
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_pddLoadDataButton)

    # Relative dose factor
    self.step3_1_rdfLineEdit = qt.QLineEdit()
    self.step3_1_calibrationRoutineLayout.addRow('Relative dose factor (RDF): ', self.step3_1_rdfLineEdit)

    # Empty row
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)

    # Monitor units
    self.step3_1_monitorUnitsLineEdit = qt.QLineEdit()
    self.step3_1_calibrationRoutineLayout.addRow("Delivered monitor units (MU's): ", self.step3_1_monitorUnitsLineEdit)

    # Averaging radius
    self.step3_1_radiusMmFromCentrePixelLineEdit = qt.QLineEdit()
    self.step3_1_radiusMmFromCentrePixelLineEdit.toolTip = "Radius of the cylinder that is extracted around central axis to get ΔR1 or ΔR2 values per depth"
    self.step3_1_calibrationRoutineLayout.addRow('Averaging radius (mm): ', self.step3_1_radiusMmFromCentrePixelLineEdit)
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)
    
    # Checkbox to enable custom line sampling
    self.step3_1_useCustomLineSampling = qt.QCheckBox()
    self.step3_1_useCustomLineSampling.setChecked(False)
    self.step3_1_useCustomLineSampling.setToolTip('Enable to sample calibration data along a custom ruler line instead of central cylinder')
    self.step3_1_calibrationRoutineLayout.addRow('Use custom line sampling: ', self.step3_1_useCustomLineSampling)
    
    # Ruler selector for calibration sampling
    self.step3_1_calibrationRulerSelector = slicer.qMRMLNodeComboBox()
    self.step3_1_calibrationRulerSelector.nodeTypes = ["vtkMRMLMarkupsLineNode"]
    self.step3_1_calibrationRulerSelector.selectNodeUponCreation = True
    self.step3_1_calibrationRulerSelector.addEnabled = True
    self.step3_1_calibrationRulerSelector.removeEnabled = True
    self.step3_1_calibrationRulerSelector.noneEnabled = True
    self.step3_1_calibrationRulerSelector.showHidden = False
    self.step3_1_calibrationRulerSelector.setMRMLScene(slicer.mrmlScene)
    self.step3_1_calibrationRulerSelector.setToolTip('Select ruler line for calibration sampling')
    self.step3_1_calibrationRulerSelector.enabled = False
    self.step3_1_calibrationRulerSelector.setProperty('baseName', 'CalibrationLine')
    self.step3_1_calibrationRoutineLayout.addRow('  Calibration ruler: ', self.step3_1_calibrationRulerSelector)
    
    # Sampling radius
    self.step3_1_lineSamplingRadiusSpinBox = qt.QDoubleSpinBox()
    self.step3_1_lineSamplingRadiusSpinBox.decimals = 1
    self.step3_1_lineSamplingRadiusSpinBox.minimum = 0.5
    self.step3_1_lineSamplingRadiusSpinBox.maximum = 50.0
    self.step3_1_lineSamplingRadiusSpinBox.value = 2.0
    self.step3_1_lineSamplingRadiusSpinBox.suffix = ' mm'
    self.step3_1_lineSamplingRadiusSpinBox.setToolTip('Radius around the line for averaging (perpendicular sampling)')
    self.step3_1_lineSamplingRadiusSpinBox.enabled = False
    self.step3_1_calibrationRoutineLayout.addRow('  Sampling radius: ', self.step3_1_lineSamplingRadiusSpinBox)

    # Align Pdd data and Calibration data based on region of interest selected
    self.step3_1_alignCalibrationCurvesButton = qt.QPushButton("Plot reference and gel PDD data")
    self.step3_1_alignCalibrationCurvesButton.toolTip = "Align PDD data with experimentaL ΔR1 or ΔR2 values (coming from calibration gel volume)"
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_alignCalibrationCurvesButton)

    # Controls to adjust alignment
    self.step3_1_adjustAlignmentControlsLayout = qt.QHBoxLayout(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_1_adjustAlignmentLabel = qt.QLabel('Manual adjustment: ')
    self.step3_1_xTranslationLabel = qt.QLabel('  X shift:')
    self.step3_1_xTranslationSpinBox = qt.QDoubleSpinBox()
    self.step3_1_xTranslationSpinBox.decimals = 2
    self.step3_1_xTranslationSpinBox.singleStep = 0.01
    self.step3_1_xTranslationSpinBox.value = 0
    self.step3_1_xTranslationSpinBox.minimum = -100000.0
    self.step3_1_xTranslationSpinBox.maximumWidth = 482
    self.step3_1_yScaleLabel = qt.QLabel('  Y scale:')
    self.step3_1_yScaleSpinBox = qt.QDoubleSpinBox()
    self.step3_1_yScaleSpinBox.decimals = 3
    self.step3_1_yScaleSpinBox.singleStep = 0.1
    self.step3_1_yScaleSpinBox.value = 1
    self.step3_1_yScaleSpinBox.minimum = 0
    self.step3_1_yScaleSpinBox.maximum = 100000
    self.step3_1_yScaleSpinBox.maximumWidth = 482
    self.step3_1_yTranslationLabel = qt.QLabel('  Y shift:')
    self.step3_1_yTranslationSpinBox = qt.QDoubleSpinBox()
    self.step3_1_yTranslationSpinBox.decimals = 2
    self.step3_1_yTranslationSpinBox.singleStep = 0.1
    self.step3_1_yTranslationSpinBox.value = 0
    self.step3_1_yTranslationSpinBox.minimum = -100000
    self.step3_1_yTranslationSpinBox.maximum = 100000
    self.step3_1_yTranslationSpinBox.maximumWidth = 482
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_adjustAlignmentLabel)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_xTranslationLabel)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_xTranslationSpinBox)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_yScaleLabel)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_yScaleSpinBox)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_yTranslationLabel)
    self.step3_1_adjustAlignmentControlsLayout.addWidget(self.step3_1_yTranslationSpinBox)
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_adjustAlignmentControlsLayout)

    # Add empty row
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)

    # Create dose information button
    self.step3_1_computeDoseFromPddButton = qt.QPushButton("Calculate dose from reference PDD")
    self.step3_1_computeDoseFromPddButton.toolTip = "Compute dose from PDD data based on RDF and MUs"
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_computeDoseFromPddButton)

    # Empty row
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)

    # Show chart of ΔR1 or ΔR2 vs. dose curve and remove selected points
    self.step3_1_deltaRVsDoseCurveControlsLayout = qt.QHBoxLayout(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_1_showDeltaRVsDoseCurveButton = qt.QPushButton("Plot ΔR1 or ΔR2 vs dose")
    self.step3_1_showDeltaRVsDoseCurveButton.toolTip = "Show ΔR1 or ΔR2 vs. Dose curve to determine the order of polynomial to fit."
    self.step3_1_removeSelectedPointsFromDeltaRVsDoseCurveButton = qt.QPushButton("Optional: Remove selected points from plot")
    self.step3_1_removeSelectedPointsFromDeltaRVsDoseCurveButton.toolTip = "Removes the selected points (typically outliers) from the ΔR1 or ΔR2 vs Dose curve so that they are omitted during polynomial fitting.\nTo select points, hold down the right mouse button and draw a selection rectangle in the chart view."
    self.step3_1_helpLabel = qt.QLabel()
    self.step3_1_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step3_1_helpLabel.maximumWidth = 24
    self.step3_1_helpLabel.toolTip = "To select points in the plot, hold down the right mouse button and draw a selection rectangle in the chart view."
    self.step3_1_deltaRVsDoseCurveControlsLayout.addWidget(self.step3_1_showDeltaRVsDoseCurveButton)
    self.step3_1_deltaRVsDoseCurveControlsLayout.addWidget(self.step3_1_removeSelectedPointsFromDeltaRVsDoseCurveButton)
    self.step3_1_deltaRVsDoseCurveControlsLayout.addWidget(self.step3_1_helpLabel)
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_deltaRVsDoseCurveControlsLayout)

    # Add empty row
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)

    # Find polynomial fit
    self.step3_1_selectOrderOfPolynomialFitButton = qt.QComboBox()
    self.step3_1_selectOrderOfPolynomialFitButton.addItem('1')
    self.step3_1_selectOrderOfPolynomialFitButton.addItem('2')
    self.step3_1_selectOrderOfPolynomialFitButton.addItem('3')
    self.step3_1_selectOrderOfPolynomialFitButton.addItem('4')
    self.step3_1_calibrationRoutineLayout.addRow('Fit with what order polynomial function:', self.step3_1_selectOrderOfPolynomialFitButton)

    self.step3_1_fitPolynomialToDeltaRVsDoseCurveButton = qt.QPushButton("Fit data and determine calibration function")
    self.step3_1_fitPolynomialToDeltaRVsDoseCurveButton.toolTip = "Finds the line of best fit based on the data and polynomial order provided"
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_fitPolynomialToDeltaRVsDoseCurveButton)

    self.step3_1_fitPolynomialResidualsLabel = qt.QLabel()
    self.step3_1_calibrationRoutineLayout.addRow(self.step3_1_fitPolynomialResidualsLabel)

    # Step 3.2: Apply calibration
    self.step3_2_applyCalibrationCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step3_2_applyCalibrationCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step3_2_applyCalibrationCollapsibleButton.text = "3.2. Apply calibration"
    self.step3_doseCalibrationCollapsibleButtonLayout.addWidget(self.step3_2_applyCalibrationCollapsibleButton)
    self.step3_2_applyCalibrationLayout = qt.QFormLayout(self.step3_2_applyCalibrationCollapsibleButton)
    self.step3_2_applyCalibrationLayout.setContentsMargins(12,4,4,4)
    self.step3_2_applyCalibrationLayout.setSpacing(4)

    # Calibration function label
    self.step3_2_calibrationFunctionLabel = qt.QLabel("Calibration function:\n(either determined from step 3.1., or can be manually input/altered)")
    self.step3_2_calibrationFunctionLabel.wordWrap = True
    self.step3_2_applyCalibrationLayout.addRow(self.step3_2_calibrationFunctionLabel)

    # Dose calibration function input fields
    self.step3_2_calibrationFunctionLayout = qt.QGridLayout(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_2_doseLabel = qt.QLabel('Dose (Gy) = ')
    self.step3_2_calibrationFunctionOrderLineEdits = []
    self.step3_2_calibrationFunctionOrder0LineEdit = qt.QLineEdit()
    self.step3_2_calibrationFunctionOrder0LineEdit.maximumWidth = 64
    self.step3_2_calibrationFunctionOrderLineEdits.append(self.step3_2_calibrationFunctionOrder0LineEdit)
    self.step3_2_calibrationFunctionOrder0Label = qt.QLabel(' ΔR1 or ΔR2<span style=" font-size:8pt; vertical-align:super;">0</span> + ')
    self.step3_2_calibrationFunctionOrder1LineEdit = qt.QLineEdit()
    self.step3_2_calibrationFunctionOrder1LineEdit.maximumWidth = 64
    self.step3_2_calibrationFunctionOrderLineEdits.append(self.step3_2_calibrationFunctionOrder1LineEdit)
    self.step3_2_calibrationFunctionOrder1Label = qt.QLabel(' ΔR1 or ΔR2<span style=" font-size:8pt; vertical-align:super;">1</span> + ')
    self.step3_2_calibrationFunctionOrder2LineEdit = qt.QLineEdit()
    self.step3_2_calibrationFunctionOrder2LineEdit.maximumWidth = 64
    self.step3_2_calibrationFunctionOrderLineEdits.append(self.step3_2_calibrationFunctionOrder2LineEdit)
    self.step3_2_calibrationFunctionOrder2Label = qt.QLabel(' ΔR1 or ΔR2<span style=" font-size:8pt; vertical-align:super;">2</span> + ')
    self.step3_2_calibrationFunctionOrder3LineEdit = qt.QLineEdit()
    self.step3_2_calibrationFunctionOrder3LineEdit.maximumWidth = 64
    self.step3_2_calibrationFunctionOrderLineEdits.append(self.step3_2_calibrationFunctionOrder3LineEdit)
    self.step3_2_calibrationFunctionOrder3Label = qt.QLabel(' ΔR1 or ΔR2<span style=" font-size:8pt; vertical-align:super;">3</span> + ')
    self.step3_2_calibrationFunctionOrder4LineEdit = qt.QLineEdit()
    self.step3_2_calibrationFunctionOrder4LineEdit.maximumWidth = 64
    self.step3_2_calibrationFunctionOrderLineEdits.append(self.step3_2_calibrationFunctionOrder4LineEdit)
    self.step3_2_calibrationFunctionOrder4Label = qt.QLabel(' ΔR1 or ΔR2<span style=" font-size:8pt; vertical-align:super;">4</span>')
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_doseLabel,0,0)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder0LineEdit,0,1)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder0Label,0,2)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder1LineEdit,0,3)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder1Label,0,4)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder2LineEdit,0,5)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder2Label,0,6)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder3LineEdit,1,1)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder3Label,1,2)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder4LineEdit,1,3)
    self.step3_2_calibrationFunctionLayout.addWidget(self.step3_2_calibrationFunctionOrder4Label,1,4)
    self.step3_2_applyCalibrationLayout.addRow(self.step3_2_calibrationFunctionLayout)

    # Export calibration polynomial coefficients to CSV
    self.step3_2_exportCalibrationToCSV = qt.QPushButton("Optional: Export calibration points to a CSV file")
    self.step3_2_exportCalibrationToCSV.toolTip = "Export ΔR1 or ΔR2 to dose calibration plot points (if points were removed, those are not exported).\nIf polynomial fitting has been done, export the coefficients as well."
    self.step3_2_applyCalibrationLayout.addRow(self.step3_2_exportCalibrationToCSV)

    # Empty row
    self.step3_1_calibrationRoutineLayout.addRow(' ', None)

    # Apply calibration button
    self.step3_2_applyCalibrationButton = qt.QPushButton("Apply calibration")
    self.step3_2_applyCalibrationButton.toolTip = "Apply fitted polynomial on MEASURED volume"
    self.step3_2_applyCalibrationLayout.addRow(self.step3_2_applyCalibrationButton)

    self.step3_2_applyCalibrationStatusLabel = qt.QLabel()
    self.step3_2_applyCalibrationLayout.addRow(' ', self.step3_2_applyCalibrationStatusLabel)

    # Add substeps in a button group
    self.step3_calibrationCollapsibleButtonGroup = qt.QButtonGroup()
    self.step3_calibrationCollapsibleButtonGroup.addButton(self.step3_1_calibrationRoutineCollapsibleButton)
    self.step3_calibrationCollapsibleButtonGroup.addButton(self.step3_2_applyCalibrationCollapsibleButton)

    # Make sure first panels appear when steps are first opened (done before connections to avoid
    # executing those steps, which are only needed when actually switching there during the workflow)
    self.step3_1_calibrationRoutineCollapsibleButton.setProperty('collapsed', False)

    # Connections
    self.step3_doseCalibrationCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep3_1_CalibrationRoutineSelected)
    self.step3_1_pddLoadDataButton.connect('clicked()', self.onLoadPddDataRead)
    self.step3_1_alignCalibrationCurvesButton.connect('clicked()', self.onAlignCalibrationCurves)
    self.step3_1_xTranslationSpinBox.connect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_yScaleSpinBox.connect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_yTranslationSpinBox.connect('valueChanged(double)', self.onAdjustAlignmentValueChanged)
    self.step3_1_useCustomLineSampling.connect('toggled(bool)', self.onToggleCustomLineSampling)
    self.step3_1_lineSamplingRadiusSpinBox.connect('valueChanged(double)', self.onLineSamplingRadiusChanged)
    self.step3_1_computeDoseFromPddButton.connect('clicked()', self.onComputeDoseFromPdd)
    self.step3_1_calibrationRoutineCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep3_1_CalibrationRoutineSelected)
    self.step3_1_showDeltaRVsDoseCurveButton.connect('clicked()', self.onShowDeltaRVsDoseCurve)
    self.step3_1_removeSelectedPointsFromDeltaRVsDoseCurveButton.connect('clicked()', self.onRemoveSelectedPointsFromDeltaRVsDoseCurve)
    self.step3_1_fitPolynomialToDeltaRVsDoseCurveButton.connect('clicked()', self.onFitPolynomialToDeltaRVsDoseCurve)
    self.step3_2_exportCalibrationToCSV.connect('clicked()', self.onExportCalibration)
    self.step3_2_applyCalibrationButton.connect('clicked()', self.onApplyCalibration)

  #------------------------------------------------------------------------------
  def setup_Step4_DoseComparison(self):
    # Step 4: Dose comparison and analysis
    self.step4_doseComparisonCollapsibleButton.setProperty('collapsedHeight', 4)
    # self.step4_doseComparisonCollapsibleButton.text = "4. 3D dose comparison"
    self.step4_doseComparisonCollapsibleButton.text = "4. 3D gamma dose comparison" #TODO: Switch to line above when more dose comparisons are added
    self.sliceletPanelLayout.addWidget(self.step4_doseComparisonCollapsibleButton)
    self.step4_doseComparisonCollapsibleButtonLayout = qt.QFormLayout(self.step4_doseComparisonCollapsibleButton)
    self.step4_doseComparisonCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_doseComparisonCollapsibleButtonLayout.setSpacing(4)

    # Info label
    self.step4_doseComparisonReferenceVolumeLabel = qt.QLabel('Calibration has not been performed!')
    self.step4_doseComparisonReferenceVolumeLabel.wordWrap = True
    self.step4_doseComparisonCollapsibleButtonLayout.addRow('Plan dose volume (reference):', self.step4_doseComparisonReferenceVolumeLabel)
    self.step4_doseComparisonEvaluatedVolumeLabel = qt.QLabel('Calibration has not been performed!')
    self.step4_doseComparisonEvaluatedVolumeLabel.wordWrap = True
    self.step4_doseComparisonCollapsibleButtonLayout.addRow('Calibrated gel volume (evaluated):', self.step4_doseComparisonEvaluatedVolumeLabel)

    # Mask segmentation selector
    self.step4_maskSegmentationSelector = slicer.qMRMLSegmentSelectorWidget()
    self.step4_maskSegmentationSelector.setMRMLScene(slicer.mrmlScene)
    self.step4_maskSegmentationSelector.noneEnabled = True
    self.step4_doseComparisonCollapsibleButtonLayout.addRow("Mask structure: ", self.step4_maskSegmentationSelector)

    # Collapsible buttons for substeps
    self.step4_1_gammaDoseComparisonCollapsibleButton = ctk.ctkCollapsibleButton()
    self.step4_1_gammaDoseComparisonCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step4_1_gammaDoseComparisonCollapsibleButton.setVisible(False) # TODO:
    self.step4_2_chiDoseComparisonCollapsibleButton = ctk.ctkCollapsibleButton() #TODO:
    self.step4_2_chiDoseComparisonCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step4_2_chiDoseComparisonCollapsibleButton.setVisible(False) # TODO:
    self.step4_3_doseDifferenceComparisonCollapsibleButton = ctk.ctkCollapsibleButton() #TODO:
    self.step4_3_doseDifferenceComparisonCollapsibleButton.setProperty('collapsedHeight', 4)
    self.step4_3_doseDifferenceComparisonCollapsibleButton.setVisible(False) # TODO:

    self.collapsibleButtonsGroupForDoseComparisonAndAnalysis = qt.QButtonGroup()
    self.collapsibleButtonsGroupForDoseComparisonAndAnalysis.addButton(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.collapsibleButtonsGroupForDoseComparisonAndAnalysis.addButton(self.step4_2_chiDoseComparisonCollapsibleButton)
    self.collapsibleButtonsGroupForDoseComparisonAndAnalysis.addButton(self.step4_3_doseDifferenceComparisonCollapsibleButton)

    # 4.1. Gamma dose comparison
    self.step4_1_gammaDoseComparisonCollapsibleButton.text = "4.1. Gamma dose comparison"
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout = qt.QFormLayout(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_doseComparisonCollapsibleButtonLayout.addRow(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.setSpacing(4)

    # Temporarily assign main layout to 4.1. gamma layout until more dose comparisons are added
    #TODO: Remove when more dose comparisons are added
    self.step4_1_gammaDoseComparisonCollapsibleButton = self.step4_doseComparisonCollapsibleButton
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout = self.step4_doseComparisonCollapsibleButtonLayout

    # DTA
    self.step4_1_dtaDistanceToleranceMmSpinBox = qt.QDoubleSpinBox()
    self.step4_1_dtaDistanceToleranceMmSpinBox.setValue(3.0)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow('Distance-to-agreement criteria (mm): ', self.step4_1_dtaDistanceToleranceMmSpinBox)

    # Dose difference tolerance criteria
    self.step4_1_doseDifferenceToleranceLayout = qt.QHBoxLayout(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_1_doseDifferenceToleranceLabelBefore = qt.QLabel('Dose difference criteria is ')
    self.step4_1_doseDifferenceTolerancePercentSpinBox = qt.QDoubleSpinBox()
    self.step4_1_doseDifferenceTolerancePercentSpinBox.setValue(3.0)
    self.step4_1_doseDifferenceToleranceLabelAfter = qt.QLabel('% of:  ')
    self.step4_1_doseDifferenceToleranceLayout.addWidget(self.step4_1_doseDifferenceToleranceLabelBefore)
    self.step4_1_doseDifferenceToleranceLayout.addWidget(self.step4_1_doseDifferenceTolerancePercentSpinBox)
    self.step4_1_doseDifferenceToleranceLayout.addWidget(self.step4_1_doseDifferenceToleranceLabelAfter)

    self.step4_1_referenceDoseLayout = qt.QVBoxLayout()
    self.step4_1_referenceDoseUseMaximumDoseRadioButton = qt.QRadioButton('the maximum dose\n(calculated from plan dose volume)')
    self.step4_1_referenceDoseUseCustomValueLayout = qt.QHBoxLayout(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_1_referenceDoseUseCustomValueGyRadioButton = qt.QRadioButton('a custom dose value (cGy):')
    self.step4_1_referenceDoseCustomValueCGySpinBox = qt.QDoubleSpinBox()
    self.step4_1_referenceDoseCustomValueCGySpinBox.value = 5.0
    self.step4_1_referenceDoseCustomValueCGySpinBox.maximum = 99999
    self.step4_1_referenceDoseCustomValueCGySpinBox.maximumWidth = 48
    self.step4_1_referenceDoseCustomValueCGySpinBox.enabled = False
    self.step4_1_referenceDoseUseCustomValueLayout.addWidget(self.step4_1_referenceDoseUseCustomValueGyRadioButton)
    self.step4_1_referenceDoseUseCustomValueLayout.addWidget(self.step4_1_referenceDoseCustomValueCGySpinBox)
    self.step4_1_referenceDoseUseCustomValueLayout.addStretch(1)
    self.step4_1_referenceDoseLayout.addWidget(self.step4_1_referenceDoseUseMaximumDoseRadioButton)
    self.step4_1_referenceDoseLayout.addLayout(self.step4_1_referenceDoseUseCustomValueLayout)
    self.step4_1_doseDifferenceToleranceLayout.addLayout(self.step4_1_referenceDoseLayout)

    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(self.step4_1_doseDifferenceToleranceLayout)

    # Analysis threshold
    self.step4_1_analysisThresholdLayout = qt.QHBoxLayout(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_1_analysisThresholdLabelBefore = qt.QLabel('Do not calculate gamma values for voxels below ')
    self.step4_1_analysisThresholdPercentSpinBox = qt.QDoubleSpinBox()
    self.step4_1_analysisThresholdPercentSpinBox.value = 0.0
    self.step4_1_analysisThresholdPercentSpinBox.maximumWidth = 48
    self.step4_1_analysisThresholdLabelAfter = qt.QLabel('% of the maximum dose,')
    self.step4_1_analysisThresholdLabelAfter.wordWrap = True
    self.step4_1_analysisThresholdLayout.addWidget(self.step4_1_analysisThresholdLabelBefore)
    self.step4_1_analysisThresholdLayout.addWidget(self.step4_1_analysisThresholdPercentSpinBox)
    self.step4_1_analysisThresholdLayout.addWidget(self.step4_1_analysisThresholdLabelAfter)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(self.step4_1_analysisThresholdLayout)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(qt.QLabel('                                            or the custom dose value (depending on selection above).'))

    # Use geometric gamma calculation
    self.step4_1_useGeometricGammaCalculation = qt.QCheckBox()
    self.step4_1_useGeometricGammaCalculation.checked = True
    self.step4_1_useGeometricGammaCalculation.setToolTip('By checking this box, gamma will be calculated according to Ju et al 2008, which finds the point with the minimum gamma value by using the normal vector between the two candidate points.')
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow('Use geometric gamma calculation: ', self.step4_1_useGeometricGammaCalculation)

    # Maximum gamma
    self.step4_1_maximumGammaSpinBox = qt.QDoubleSpinBox()
    self.step4_1_maximumGammaSpinBox.setValue(2.0)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow('Upper bound for gamma calculation: ', self.step4_1_maximumGammaSpinBox)

    # Gamma volume selector
    self.step4_1_gammaVolumeSelectorLayout = qt.QHBoxLayout(self.step4_1_gammaDoseComparisonCollapsibleButton)
    self.step4_1_gammaVolumeSelector = slicer.qMRMLNodeComboBox()
    self.step4_1_gammaVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.step4_1_gammaVolumeSelector.addEnabled = True
    self.step4_1_gammaVolumeSelector.removeEnabled = False
    self.step4_1_gammaVolumeSelector.setMRMLScene( slicer.mrmlScene )
    self.step4_1_gammaVolumeSelector.setToolTip( "Select output gamma volume" )
    self.step4_1_gammaVolumeSelector.setProperty('baseName', 'GammaVolume')
    self.step4_1_helpLabel = qt.QLabel()
    self.step4_1_helpLabel.pixmap = qt.QPixmap(':Icons/Help.png')
    self.step4_1_helpLabel.maximumWidth = 24
    self.step4_1_helpLabel.toolTip = "A gamma volume must be selected to contain the output. You can create a new volume by selecting 'Create new Volume'"
    self.step4_1_gammaVolumeSelectorLayout.addWidget(self.step4_1_gammaVolumeSelector)
    self.step4_1_gammaVolumeSelectorLayout.addWidget(self.step4_1_helpLabel)
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow("Gamma volume: ", self.step4_1_gammaVolumeSelectorLayout)

    self.step4_1_computeGammaButton = qt.QPushButton('Calculate gamma volume')
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(self.step4_1_computeGammaButton)

    self.step4_1_gammaStatusLabel = qt.QLabel()
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(self.step4_1_gammaStatusLabel)

    self.step4_1_showGammaReportButton = qt.QPushButton('Show report')
    self.step4_1_showGammaReportButton.enabled = False
    self.step4_1_gammaDoseComparisonCollapsibleButtonLayout.addRow(self.step4_1_showGammaReportButton)

    # 4.2. Chi dose comparison
    self.step4_2_chiDoseComparisonCollapsibleButton.text = "4.2. Chi dose comparison"
    self.step4_2_chiDoseComparisonCollapsibleButtonLayout = qt.QFormLayout(self.step4_2_chiDoseComparisonCollapsibleButton)
    self.step4_doseComparisonCollapsibleButtonLayout.addRow(self.step4_2_chiDoseComparisonCollapsibleButton)
    self.step4_2_chiDoseComparisonCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_2_chiDoseComparisonCollapsibleButtonLayout.setSpacing(4)

    # 4.3. Dose difference comparison
    self.step4_3_doseDifferenceComparisonCollapsibleButton.text = "4.3. Dose difference comparison"
    self.step4_3_doseDifferenceComparisonCollapsibleButtonLayout = qt.QFormLayout(self.step4_3_doseDifferenceComparisonCollapsibleButton)
    self.step4_doseComparisonCollapsibleButtonLayout.addRow(self.step4_3_doseDifferenceComparisonCollapsibleButton)
    self.step4_3_doseDifferenceComparisonCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.step4_3_doseDifferenceComparisonCollapsibleButtonLayout.setSpacing(4)

    # Make sure first panels appear when steps are first opened (done before connections to avoid
    # executing those steps, which are only needed when actually switching there during the workflow)
    #self.step4_1_gammaDoseComparisonCollapsibleButton.setProperty('collapsed',False) #TODO: Uncomment when adding more dose comparisons
    self.step4_1_referenceDoseUseMaximumDoseRadioButton.setChecked(True)

    # Connections
    self.step4_doseComparisonCollapsibleButton.connect('contentsCollapsed(bool)', self.onStep4_DoseComparisonSelected)
    self.step4_maskSegmentationSelector.connect('currentNodeChanged(vtkMRMLNode*)', self.onStep4_MaskSegmentationSelectionChanged)
    self.step4_maskSegmentationSelector.connect('currentSegmentChanged(QString)', self.onStep4_MaskSegmentSelectionChanged)
    self.step4_1_referenceDoseUseMaximumDoseRadioButton.connect('toggled(bool)', self.onUseMaximumDoseRadioButtonToggled)
    self.step4_1_computeGammaButton.connect('clicked()', self.onGammaDoseComparison)
    self.step4_1_showGammaReportButton.connect('clicked()', self.onShowGammaReport)

  #------------------------------------------------------------------------------
  def setup_StepT1_lineProfileCollapsibleButton(self):
    # Step T1: Line profile tool
    self.stepT1_lineProfileCollapsibleButton.setProperty('collapsedHeight', 4)
    self.stepT1_lineProfileCollapsibleButton.text = "Tool: Line profile"
    self.sliceletPanelLayout.addWidget(self.stepT1_lineProfileCollapsibleButton)
    self.stepT1_lineProfileCollapsibleButtonLayout = qt.QFormLayout(self.stepT1_lineProfileCollapsibleButton)
    self.stepT1_lineProfileCollapsibleButtonLayout.setContentsMargins(12,4,4,4)
    self.stepT1_lineProfileCollapsibleButtonLayout.setSpacing(4)

    # Ruler creator
    self.stepT1_rulerCreationButton = slicer.qSlicerMouseModeToolBar()
    self.stepT1_rulerCreationButton.setApplicationLogic(slicer.app.applicationLogic())
    self.stepT1_rulerCreationButton.setMRMLScene(slicer.app.mrmlScene())
    self.stepT1_rulerCreationButton.setToolTip( "Create ruler (line segment) for line profile" )
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow("Create ruler: ", self.stepT1_rulerCreationButton)

    # Input ruler selector
    self.stepT1_inputRulerSelector = slicer.qMRMLNodeComboBox()
    self.stepT1_inputRulerSelector.nodeTypes = ["vtkMRMLMarkupsLineNode", "vtkMRMLAnnotationRulerNode"]
    self.stepT1_inputRulerSelector.selectNodeUponCreation = True
    self.stepT1_inputRulerSelector.addEnabled = True
    self.stepT1_inputRulerSelector.removeEnabled = True
    self.stepT1_inputRulerSelector.noneEnabled = False
    self.stepT1_inputRulerSelector.showHidden = False
    self.stepT1_inputRulerSelector.showChildNodeTypes = False
    self.stepT1_inputRulerSelector.setMRMLScene( slicer.mrmlScene )
    self.stepT1_inputRulerSelector.setToolTip( "Pick the ruler that defines the sampling line." )
    self.stepT1_inputRulerSelector.setProperty('baseName', 'LineProfile')
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow("Input ruler: ", self.stepT1_inputRulerSelector)

    # Line sampling resolution in mm
    self.stepT1_lineResolutionMmSliderWidget = ctk.ctkSliderWidget()
    self.stepT1_lineResolutionMmSliderWidget.decimals = 1
    self.stepT1_lineResolutionMmSliderWidget.singleStep = 0.1
    self.stepT1_lineResolutionMmSliderWidget.minimum = 0.1
    self.stepT1_lineResolutionMmSliderWidget.maximum = 2
    self.stepT1_lineResolutionMmSliderWidget.value = 0.5
    self.stepT1_lineResolutionMmSliderWidget.setToolTip("Sampling density along the line in mm")
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow("Line resolution (mm): ", self.stepT1_lineResolutionMmSliderWidget)

    # Show/hide legend checkbox
    self.stepT1_lineProfileLegendVisibilityCheckbox = qt.QCheckBox()
    self.stepT1_lineProfileLegendVisibilityCheckbox.checked = True
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow('Show legend: ', self.stepT1_lineProfileLegendVisibilityCheckbox)

    # Create line profile button
    self.stepT1_createLineProfileButton = qt.QPushButton("Create line profile")
    self.stepT1_createLineProfileButton.toolTip = "Compute and show line profile"
    self.stepT1_createLineProfileButton.enabled = False
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow(self.stepT1_createLineProfileButton)
    self.onSelectLineProfileParameters()

    # Export line profiles to CSV button
    self.stepT1_exportLineProfilesToCSV = qt.QPushButton("Export line profiles to CSV")
    self.stepT1_exportLineProfilesToCSV.toolTip = "Export calculated line profiles to CSV"
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow(self.stepT1_exportLineProfilesToCSV)

    # Hint label
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow(' ', None)
    self.stepT1_lineProfileHintLabel = qt.QLabel("Hint: Full screen plot view is available in the layout selector tab (top one)")
    self.stepT1_lineProfileCollapsibleButtonLayout.addRow(self.stepT1_lineProfileHintLabel)

    # Connections
    self.stepT1_lineProfileCollapsibleButton.connect('contentsCollapsed(bool)', self.onStepT1_LineProfileSelected)
    self.stepT1_lineProfileLegendVisibilityCheckbox.connect('toggled(bool)', self.onLegendVisibilityToggled)
    self.stepT1_createLineProfileButton.connect('clicked(bool)', self.onCreateLineProfileButton)
    self.stepT1_inputRulerSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelectLineProfileParameters)
    self.stepT1_exportLineProfilesToCSV.connect('clicked()', self.onExportLineProfiles)

  #
  # -----------------------
  # Event handler functions
  # -----------------------
  #
  def onViewSelect(self, layoutIndex):
    if layoutIndex == 0:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    elif layoutIndex == 1:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView)
    elif layoutIndex == 2:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
    elif layoutIndex == 3:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutTabbedSliceView)
    elif layoutIndex == 4:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutDual3DView)
    elif layoutIndex == 5:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpPlotView)
    elif layoutIndex == 6:
       self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpPlotView)

  #------------------------------------------------------------------------------
  def onClinicalModeSelect(self, toggled):
    if self.step0_clinicalModeRadioButton.isChecked():
      self.mode = 'Clinical'
    elif self.step0_preclinicalModeRadioButton.isChecked():
      self.mode = 'Preclinical'
    
    self.step3_1_showDeltaRVsDoseCurveButton.setText("Plot ΔR1 or ΔR2 vs dose")
    self.step3_1_showDeltaRVsDoseCurveButton.toolTip = "Show ΔR1 or ΔR2 vs. Dose curve to determine the order of polynomial to fit."

  #------------------------------------------------------------------------------
  def onLoadNonDicomData(self):
    slicer.util.openAddDataDialog()

  #------------------------------------------------------------------------------
  # Step 1
  #------------------------------------------------------------------------------
  def onStep1_LoadDataCollapsed(self, collapsed):
    if collapsed == True:
      # Save selections to member variables when switching away from load data step
      self.planningVolumeNode = self.planningSelector.currentNode()
      self.planDoseVolumeNode = self.planDoseSelector.currentNode()
      self.igrtVolumeNode = self.igrtSelector.currentNode()
      self.planStructuresNode = self.planStructuresSelector.currentNode()

  #------------------------------------------------------------------------------
  # Step 2
  #------------------------------------------------------------------------------
  def onStep2_RegistrationCollapsed(self, collapsed):
    # Make sure the functions handling entering the fiducial selection panels are called when entering the outer panel
    if collapsed == False:
      if self.step2_1_planningToIGRTRegistrationCollapsibleButton.collapsed == False:
        self.onStep2_1_PlanningToIGRTRegistrationSelected(False)
      elif self.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton.collapsed == False:
        self.onStep2_2_MeasuredDoseToIGRTRegistrationSelected(False)

      # Make sure current registration type is properly set up
      self.onAutomaticPlanningToIGRTRegistrationToggled(self.step2_1_registrationTypeAutomaticRadioButton.checked)

  #------------------------------------------------------------------------------
  def onStep2_1_PlanningToIGRTRegistrationSelected(self, collapsed):
    # Make sure the functions handling entering the fiducial selection panels are called when entering the outer panel
    if collapsed == False:
      if self.step2_1_1_igrtFiducialSelectionCollapsibleButton.collapsed == False:
        self.onStep2_1_1_IGRTFiducialCollectionSelected(False)
      elif self.step2_1_2_planningFiducialSelectionCollapsibleButton.collapsed == False:
        self.onStep2_1_2_PlanningFiducialCollectionSelected(False)

        # Make sure the fiducials used for this step are visible
        if self.igrtMarkupsFiducialNode_WithPlan and self.igrtMarkupsFiducialNode_WithPlan.GetDisplayNode():
          self.igrtMarkupsFiducialNode_WithPlan.GetDisplayNode().SetVisibility(1)
        if self.planningMarkupsFiducialNode and self.planningMarkupsFiducialNode.GetDisplayNode():
          self.planningMarkupsFiducialNode.GetDisplayNode().SetVisibility(1)
        # Hide the fiducials from step 2.2 in case the user switches back
        if self.igrtMarkupsFiducialNode_WithMeasured and self.igrtMarkupsFiducialNode_WithMeasured.GetDisplayNode():
          self.igrtMarkupsFiducialNode_WithMeasured.GetDisplayNode().SetVisibility(0)
        if self.measuredMarkupsFiducialNode and self.measuredMarkupsFiducialNode.GetDisplayNode():
          self.measuredMarkupsFiducialNode.GetDisplayNode().SetVisibility(0)

  #------------------------------------------------------------------------------
  def onStep2_1_1_IGRTFiducialCollectionSelected(self, collapsed):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    interactionNode = appLogic.GetInteractionNode()

    if collapsed == False:
      # Setup visualization for easy review of registration result
      self.step2_SetupVisualization()

      # Turn on persistent fiducial placement mode
      interactionNode.SwitchToPersistentPlaceMode()

      # Select IGRT fiducials node
      self.step2_1_1_igrtFiducialList.setCurrentNode(self.igrtMarkupsFiducialNode_WithPlan)
      self.step2_1_1_igrtFiducialList.activate()

      # Automatically show IGRT volume (show nothing if not present)
      if self.igrtVolumeNode is not None:
        selectionNode.SetActiveVolumeID(self.igrtVolumeNode.GetID())
      else:
        selectionNode.SetActiveVolumeID(None)
        slicer.util.errorDisplay('IGRT volume not selected!\nPlease return to first step and make the assignment')
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()
    else:
      # Turn off fiducial place mode
      interactionNode.SwitchToViewTransformMode()

  #------------------------------------------------------------------------------
  def onStep2_1_2_PlanningFiducialCollectionSelected(self, collapsed):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    interactionNode = appLogic.GetInteractionNode()

    if collapsed == False:
      # Turn on persistent fiducial placement mode
      interactionNode.SwitchToPersistentPlaceMode()

      # Select planning fiducials node
      self.step2_1_2_planningFiducialList.setCurrentNode(self.planningMarkupsFiducialNode)
      self.step2_1_2_planningFiducialList.activate()

      # Automatically show planning volume (show nothing if not present)
      if self.planningVolumeNode is not None:
        selectionNode.SetActiveVolumeID(self.planningVolumeNode.GetID())
      else:
        selectionNode.SetActiveVolumeID(None)
        slicer.util.errorDisplay('Planning volume not selected!\nPlease return to first step and make the assignment')
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()
    else:
      # Turn off fiducial place mode
      interactionNode.SwitchToViewTransformMode()

  #------------------------------------------------------------------------------
  def onStep2_2_MeasuredDoseToIGRTRegistrationSelected(self, collapsed):
    # Make sure the functions handling entering the fiducial selection panels are called when entering the outer panel
    if collapsed == False:
      if self.step2_2_1_igrtFiducialSelectionCollapsibleButton.collapsed == False:
        self.onStep2_2_1_IGRTFiducialCollectionSelected(False)
      elif self.step2_2_2_measuredFiducialSelectionCollapsibleButton.collapsed == False:
        self.onStep2_2_2_MeasuredFiducialCollectionSelected(False)

        # Make sure the fiducials used for this step are visible
        if self.igrtMarkupsFiducialNode_WithMeasured and self.igrtMarkupsFiducialNode_WithMeasured.GetDisplayNode():
          self.igrtMarkupsFiducialNode_WithMeasured.GetDisplayNode().SetVisibility(1)
        if self.measuredMarkupsFiducialNode and self.measuredMarkupsFiducialNode.GetDisplayNode():
          self.measuredMarkupsFiducialNode.GetDisplayNode().SetVisibility(1)
        # Hide the fiducials from step 2.1 in case landmark mode was used
        if self.igrtMarkupsFiducialNode_WithPlan and self.igrtMarkupsFiducialNode_WithPlan.GetDisplayNode():
          self.igrtMarkupsFiducialNode_WithPlan.GetDisplayNode().SetVisibility(0)
        if self.planningMarkupsFiducialNode and self.planningMarkupsFiducialNode.GetDisplayNode():
          self.planningMarkupsFiducialNode.GetDisplayNode().SetVisibility(0)

  #------------------------------------------------------------------------------
  def onStep2_2_1_IGRTFiducialCollectionSelected(self, collapsed):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    interactionNode = appLogic.GetInteractionNode()

    if collapsed == False:
      # Turn on persistent fiducial placement mode
      interactionNode.SwitchToPersistentPlaceMode()

      # Select IGRT fiducials node
      self.step2_2_1_igrtFiducialList.setCurrentNode(self.igrtMarkupsFiducialNode_WithMeasured)
      self.step2_2_1_igrtFiducialList.activate()

      # Automatically show IGRT volume (show nothing if not present)
      if self.igrtVolumeNode is not None:
        selectionNode.SetActiveVolumeID(self.igrtVolumeNode.GetID())
      else:
        selectionNode.SetActiveVolumeID(None)
        slicer.util.errorDisplay('IGRT volume not selected!\nPlease return to first step and make the assignment')
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()
    else:
      # Turn off fiducial place mode
      interactionNode.SwitchToViewTransformMode()

  #------------------------------------------------------------------------------
  def onStep2_2_2_MeasuredFiducialCollectionSelected(self, collapsed):
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      interactionNode = appLogic.GetInteractionNode()

      if collapsed == False:
        # Turn on persistent fiducial placement mode
        interactionNode.SwitchToPersistentPlaceMode()

        # Select MEASURED fiducials node
        self.step2_2_2_measuredFiducialList.setCurrentNode(self.measuredMarkupsFiducialNode)
        self.step2_2_2_measuredFiducialList.activate()

        # Default to DeltaR map if available, otherwise fall back to measuredVolumeNode
        deltaRNode = slicer.mrmlScene.GetFirstNodeByName("DeltaR_Map")
        defaultVolume = deltaRNode if deltaRNode is not None else self.measuredVolumeNode

        if defaultVolume is not None:
          self.step2_2_2_backgroundVolumeSelector.setCurrentNode(defaultVolume)
          selectionNode.SetActiveVolumeID(defaultVolume.GetID())
        else:
          selectionNode.SetActiveVolumeID(None)
          slicer.util.errorDisplay('No volume found! Please complete Step 1 first.')
        selectionNode.SetSecondaryVolumeID(None)
        appLogic.PropagateVolumeSelection()
      else:
        # Turn off fiducial place mode
        interactionNode.SwitchToViewTransformMode()

  #------------------------------------------------------------------------------
  def onMeasuredFiducialBackgroundVolumeChanged(self, node):
    if node is None:
      return
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(node.GetID())
    selectionNode.SetSecondaryVolumeID(None)
    appLogic.PropagateVolumeSelection()

  #------------------------------------------------------------------------------
  def onAutomaticPlanningToIGRTRegistrationToggled(self, automaticSelected):
    self.step2_1_planningToIGRTRegistrationFrame.setVisible(automaticSelected)
    self.step2_1_landmarkPlanningToIGRTRegistrationFrame.setVisible(not automaticSelected)

    if automaticSelected:
      # Turn off fiducial place mode
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      interactionNode = appLogic.GetInteractionNode()
      interactionNode.SwitchToViewTransformMode()
    else:
      # Make sure landmark mode is set up (fiducial placement mode, shown volumes)
      self.step2_1_1_igrtFiducialSelectionCollapsibleButton.setProperty('collapsed', False)
      self.onStep2_1_1_IGRTFiducialCollectionSelected(False)

  #------------------------------------------------------------------------------
  def onAutomaticMeasuredToIgrtRegistrationToggled(self, automaticSelected):
    self.step2_2_automaticMeasuredToIgrtRegistrationFrame.setVisible(automaticSelected)
    self.step2_2_landmarkMeasuredToIgrtRegistrationFrame.setVisible(not automaticSelected)

    if automaticSelected:
      appLogic = slicer.app.applicationLogic()
      interactionNode = appLogic.GetInteractionNode()
      interactionNode.SwitchToViewTransformMode()
    else:
      self.step2_2_1_igrtFiducialSelectionCollapsibleButton.setProperty('collapsed', False)
      self.onStep2_2_1_IGRTFiducialCollectionSelected(False)

  #------------------------------------------------------------------------------
  def step2_SetupVisualization(self):
    # Set color to the IGRT volume
    if self.igrtVolumeNode is not None:
      igrtVolumeDisplayNode = self.igrtVolumeNode.GetDisplayNode()
      colorNode = slicer.util.getNode('Green')
      igrtVolumeDisplayNode.SetAndObserveColorNodeID(colorNode.GetID())
    else:
      slicer.util.errorDisplay('IGRT volume not selected!\nPlease return to first step and make the assignment')
      return

    # Set transparency to the IGRT volume
    compositeNodes = slicer.util.getNodes("vtkMRMLSliceCompositeNode*")
    for compositeNode in compositeNodes.values():
      compositeNode.SetForegroundOpacity(0.5)
    # Hide structures for sake of speed, and show only outlines for better dose visibility
    if self.planStructuresNode and self.planStructuresNode.GetDisplayNode():
      self.planStructuresNode.GetDisplayNode().SetVisibility2DFill(False)
      self.planStructuresNode.GetDisplayNode().SetVisibility(0)
    # Hide beam models
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    planNodes = slicer.util.getNodes('vtkMRMLRTPlanNode*')
    for planNode in planNodes.values():
      planSh = shNode.GetItemByDataNode(planNode)
      if planSh:
        shNode.SetDisplayVisibilityForBranch(planSh, 0)

  #------------------------------------------------------------------------------
  def onPlanningToIGRTAutomaticRegistration(self):
    # Check required volumes are assigned
    if self.igrtVolumeNode is None:
      slicer.util.errorDisplay('IGRT volume not selected!\nPlease return to first step and make the assignment')
      return
    if self.planningVolumeNode is None:
      slicer.util.errorDisplay('Planning volume not selected!\nPlease return to first step and make the assignment')
      return
    if self.planDoseVolumeNode is None:
      slicer.util.errorDisplay('Plan dose volume not selected!\nPlease return to first step and make the assignment')
      return

    # Start registration
    igrtVolumeID = self.igrtVolumeNode.GetID()
    planningVolumeID = self.planningVolumeNode.GetID()
    planDoseVolumeID = self.planDoseVolumeNode.GetID()
    igrtToPlanningTransformNode = self.logic.registerPlanningToIGRTAutomatic(planningVolumeID, igrtVolumeID)

    # Apply transform to planning volume and plan dose
    self.planningVolumeNode.SetAndObserveTransformNodeID(igrtToPlanningTransformNode.GetID())
    if planningVolumeID != planDoseVolumeID:
        self.planDoseVolumeNode.SetAndObserveTransformNodeID(igrtToPlanningTransformNode.GetID())
    else:
        logging.warning('The selected nodes are the same for planning volume and plan dose')

    # Check if registration succeeded
    if igrtToPlanningTransformNode is not None:
        qt.QMessageBox.information(None, "Success", "Planning volume to IGRT volume registration completed successfully.")
    else:
        qt.QMessageBox.warning(None, "Registration Failed", "Planning volume to IGRT volume registration did not complete successfully.")

    # Apply transform to plan structures
    if self.planStructuresNode:
      self.planStructuresNode.SetAndObserveTransformNodeID(igrtToPlanningTransformNode.GetID())

    # Show the two volumes for visual evaluation of the registration
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(planningVolumeID)
    selectionNode.SetSecondaryVolumeID(igrtVolumeID)
    appLogic.PropagateVolumeSelection()

    # Setup visualization for easy review of registration result
    self.step2_SetupVisualization()

    # Set transforms to slider widgets
    self.step2_1_translationSliders.setMRMLTransformNode(igrtToPlanningTransformNode)
    self.step2_1_rotationSliders.setMRMLTransformNode(igrtToPlanningTransformNode)

    # Change single step size to 0.5mm in the translation controls
    sliders = slicer.util.findChildren(widget=self.step2_1_translationSliders, className='qMRMLLinearTransformSlider')
    for slider in sliders:
      slider.singleStep = 0.5

    return igrtToPlanningTransformNode

  #------------------------------------------------------------------------------
  def onPlanningToIGRTLandmarkRegistration(self):
    # Ensure nodes are assigned
    if self.planningVolumeNode is None:
        self.planningVolumeNode = self.planningSelector.currentNode()
    if self.planDoseVolumeNode is None:
        self.planDoseVolumeNode = self.planDoseSelector.currentNode()
    if self.planningVolumeNode is None:
        qt.QMessageBox.warning(None, 'Warning', 'No planning volume selected. Please return to step 1.')
        return
    igrtToPlanningTransformNode, errorRms = self.logic.registerPlanningToIGRTLandmark(self.planningMarkupsFiducialNode.GetID(), self.igrtMarkupsFiducialNode_WithPlan.GetID())

    # Show registration error on GUI
    if errorRms:
      self.step2_1_3_planningToIGRTFiducialRegistrationErrorLabel.setText(f"{float(errorRms):.6f} mm")
    else:
      self.step2_1_3_planningToIGRTFiducialRegistrationErrorLabel.setText("Registration failed")
      return

    # self.step2_1_3_planningToIGRTFiducialRegistrationErrorLabel.setText(str(errorRms) + ' mm')

    # Apply transform to planning volume and plan dose
    self.planningVolumeNode.SetAndObserveTransformNodeID(igrtToPlanningTransformNode.GetID())
    if self.planningVolumeNode != self.planDoseVolumeNode:
      self.planDoseVolumeNode.SetAndObserveTransformNodeID(igrtToPlanningTransformNode.GetID())
    else:
      logging.warning('The selected nodes are the same for planning volume and plan dose')

    # Apply transform to plan structures
    if self.planStructuresNode:
      self.planStructuresNode.SetAndObserveTransformNodeID(igrtToPlanningTransformNode.GetID())

    # Show both volumes in the 2D views
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(self.planningVolumeNode.GetID())
    selectionNode.SetSecondaryVolumeID(self.igrtVolumeNode.GetID())
    appLogic.PropagateVolumeSelection()

    return igrtToPlanningTransformNode

  #------------------------------------------------------------------------------
  def onMeasuredToIgrtRegistration(self):
    errorRms = self.logic.registerMeasuredToIGRT(self.measuredMarkupsFiducialNode.GetID(), self.igrtMarkupsFiducialNode_WithMeasured.GetID())

    # Show registration error on GUI
    if errorRms:
      self.step2_2_3_measuredToIgrtFiducialRegistrationErrorLabel.setText(f"{float(errorRms):.6f} mm")
    else:
      self.step2_2_3_measuredToIgrtFiducialRegistrationErrorLabel.setText("Registration failed")
      return

    #self.step2_2_3_measuredToIgrtFiducialRegistrationErrorLabel.setText(str(errorRms) + ' mm')

    # Apply transform to the volume where fiducials were actually placed on, then propagate to DeltaR_Map and measuredVolumeNode for downstream calibration consistency.
    igrtToMeasuredTransformNode = slicer.util.getNode(self.logic.igrtToMeasuredTransformName)

    fiducialSourceVolume = self.step2_2_2_backgroundVolumeSelector.currentNode()
    if fiducialSourceVolume is None:
      if self.step1_2_1_1_useGRECheckBox.isChecked():
        fiducialSourceVolume = self.step1_2_1_postScanSelector.currentNode()
      else:
        fiducialSourceVolume = self.step1_2_1_1_r1PostSelector.currentNode() or self.step1_2_1_postScanSelector.currentNode()

    if fiducialSourceVolume is not None:
      fiducialSourceVolume.SetAndObserveTransformNodeID(igrtToMeasuredTransformNode.GetID())

    deltaRNode = slicer.mrmlScene.GetFirstNodeByName("DeltaR_Map")
    if deltaRNode is not None:
      deltaRNode.SetAndObserveTransformNodeID(igrtToMeasuredTransformNode.GetID())
    if self.measuredVolumeNode is not None and slicer.mrmlScene.GetNodeByID(self.measuredVolumeNode.GetID()) is not None:
      self.measuredVolumeNode.SetAndObserveTransformNodeID(igrtToMeasuredTransformNode.GetID())

    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(self.igrtVolumeNode.GetID())
    # deltaRNode = slicer.mrmlScene.GetFirstNodeByName("DeltaR_Map")
    if deltaRNode is not None:
      secondaryID = deltaRNode.GetID()
    elif self.measuredVolumeNode is not None:
      secondaryID = self.measuredVolumeNode.GetID()
    else:
      slicer.util.errorDisplay('No measured volume or DeltaR map found! Please complete Step 1 first.')
      return
    selectionNode.SetSecondaryVolumeID(secondaryID)
    appLogic.PropagateVolumeSelection()

    qt.QMessageBox.information(None, "Done", "Register MEASURED to IGRT volume using fiducial registration finished.")

    return igrtToMeasuredTransformNode

  #------------------------------------------------------------------------------
  def onMeasuredToIgrtAutomaticRegistration(self):
    # Check required volumes are assigned
    if self.measuredVolumeNode is None:
      slicer.util.errorDisplay('Measured gel volume not selected!\nPlease return to first step and make the assignment')
      return
    if self.igrtVolumeNode is None:
      slicer.util.errorDisplay('IGRT volume not selected!\nPlease return to first step and make the assignment')
      return

    # Start registration
    igrtVolumeID = self.igrtVolumeNode.GetID()
    measuredVolumeID = self.measuredVolumeNode.GetID()
    igrtToMeasuredTransformNode = self.logic.registerMeasuredToIGRTAutomatic(measuredVolumeID, igrtVolumeID)

    # Apply transform to measured volume
    self.measuredVolumeNode.SetAndObserveTransformNodeID(igrtToMeasuredTransformNode.GetID())

    # Check if registration succeeded
    if igrtToMeasuredTransformNode is not None:
      qt.QMessageBox.information(None, "Success", "Measured gel volume to IGRT volume registration completed successfully.")
    else:
      qt.QMessageBox.warning(None, "Registration Failed", "Measured gel volume to IGRT volume registration did not complete successfully.")
      return

    # Show the two volumes for visual evaluation of the registration
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(measuredVolumeID)
    selectionNode.SetSecondaryVolumeID(igrtVolumeID)
    appLogic.PropagateVolumeSelection()

    # Set transforms to slider widgets
    self.step2_2_translationSliders.setMRMLTransformNode(igrtToMeasuredTransformNode)
    self.step2_2_rotationSliders.setMRMLTransformNode(igrtToMeasuredTransformNode)

    # Change single step size to 0.5mm in the translation controls
    sliders = slicer.util.findChildren(widget=self.step2_2_translationSliders, className='qMRMLLinearTransformSlider')
    for slider in sliders:
      slider.singleStep = 0.5

    return igrtToMeasuredTransformNode

  #------------------------------------------------------------------------------
  # Step 3
  #------------------------------------------------------------------------------
  def onLoadPddDataRead(self):
    fileName = qt.QFileDialog.getOpenFileName(0, 'Open PDD data file', '', 'CSV with COMMA ( *.csv )')
    if fileName is not None and fileName != '':
      success = self.logic.loadPdd(fileName)
      if success == True:
        qt.QMessageBox.information(None, "Success", "PDD loaded successfully.")
      else:
        qt.QMessageBox.critical(None, "Error", "PDD loading failed!")

  #------------------------------------------------------------------------------
  def onStep3_1_CalibrationRoutineSelected(self, collapsed):
    if collapsed == False:
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      if self.calibrationVolumeNode is not None:
        selectionNode.SetActiveVolumeID(self.calibrationVolumeNode.GetID())
      else:
        selectionNode.SetActiveVolumeID(None)
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()

  #------------------------------------------------------------------------------
  def parseCalibrationVolume(self):
    # Check if using custom line sampling
    if self.step3_1_useCustomLineSampling.isChecked():
        if not self.step3_1_calibrationRulerSelector.currentNode():
            slicer.util.errorDisplay('Please select a ruler for custom line sampling')
            return False
        
        if not self.calibrationVolumeNode:
            slicer.util.errorDisplay('No calibration volume selected!')
            return False
        
        # Use custom line sampling
        rulerNode = self.step3_1_calibrationRulerSelector.currentNode()
        samplingRadius = self.step3_1_lineSamplingRadiusSpinBox.value
        success = self.logic.sampleCalibrationAlongLine(self.calibrationVolumeNode, rulerNode, samplingRadius)
        
        if not success:
            slicer.util.errorDisplay('Failed to sample calibration data along line')
            return False
        return True
    
    # Use original central cylinder method
    else:
        radiusOfCentreCircleText = self.step3_1_radiusMmFromCentrePixelLineEdit.text
        radiusOfCentreCircleFloat = 0
        if radiusOfCentreCircleText.isnumeric():
            radiusOfCentreCircleFloat = float(radiusOfCentreCircleText)
        else:
            slicer.util.errorDisplay('Invalid averaging radius!')
            return False

        if not self.calibrationVolumeNode:
            slicer.util.errorDisplay('No calibration volume selected!')
            return False

        success = self.logic.getMeanDeltaROfCentralCylinder(self.calibrationVolumeNode.GetID(), radiusOfCentreCircleFloat)
        if success == False:
            slicer.util.errorDisplay('Calibration volume parsing failed!')
        return success

  #------------------------------------------------------------------------------
  def createCalibrationCurvesWindow(self):
    # Set up window to be used for displaying data
    self.calibrationCurveChartView = vtk.vtkContextView()
    self.calibrationCurveChartView.GetRenderer().SetBackground(1,1,1)
    self.calibrationCurveChart = vtk.vtkChartXY()
    self.calibrationCurveChartView.GetScene().AddItem(self.calibrationCurveChart)

  #------------------------------------------------------------------------------
  def showCalibrationCurves(self):
    # Create calibration mean ΔR1 or ΔR2 plot
    self.calibrationCurveDataTable = vtk.vtkTable()
    calibrationNumberOfRows = self.logic.calibrationDataArray.shape[0]

    calibrationDepthArray = vtk.vtkDoubleArray()
    calibrationDepthArray.SetName("Depth (cm)")
    self.calibrationCurveDataTable.AddColumn(calibrationDepthArray)
    calibrationMeanDeltaRArray = vtk.vtkDoubleArray()
    calibrationMeanDeltaRArray.SetName("Calibration data (mean ΔR1 or ΔR2, s^-1)")
    self.calibrationCurveDataTable.AddColumn(calibrationMeanDeltaRArray)

    self.calibrationCurveDataTable.SetNumberOfRows(calibrationNumberOfRows)
    for rowIndex in range(calibrationNumberOfRows):
      self.calibrationCurveDataTable.SetValue(rowIndex, 0, self.logic.calibrationDataArray[rowIndex, 0])
      self.calibrationCurveDataTable.SetValue(rowIndex, 1, self.logic.calibrationDataArray[rowIndex, 1])
      # self.calibrationCurveDataTable.SetValue(rowIndex, 2, self.logic.calibrationDataArray[rowIndex, 2])

    # Comment out if you don't want to plot the red line
    if hasattr(self, 'calibrationMeanDeltaRLine'):
      self.calibrationCurveChart.RemovePlotInstance(self.calibrationMeanDeltaRLine)
    self.calibrationMeanDeltaRLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.LINE)
    self.calibrationMeanDeltaRLine.SetInputData(self.calibrationCurveDataTable, 0, 1)
    self.calibrationMeanDeltaRLine.SetColor(255, 0, 0, 255)
    self.calibrationMeanDeltaRLine.SetWidth(2.0)

    # Create Pdd plot
    self.pddDataTable = vtk.vtkTable()
    pddNumberOfRows = self.logic.pddDataArray.shape[0]
    pddDepthArray = vtk.vtkDoubleArray()
    pddDepthArray.SetName("Depth (cm)")
    self.pddDataTable.AddColumn(pddDepthArray)
    pddValueArray = vtk.vtkDoubleArray()
    pddValueArray.SetName("PDD (percent depth dose)")
    self.pddDataTable.AddColumn(pddValueArray)

    self.pddDataTable.SetNumberOfRows(pddNumberOfRows)
    for pddDepthCounter in range(pddNumberOfRows):
      self.pddDataTable.SetValue(pddDepthCounter, 0, self.logic.pddDataArray[pddDepthCounter, 0])
      self.pddDataTable.SetValue(pddDepthCounter, 1, self.logic.pddDataArray[pddDepthCounter, 1])

    if hasattr(self, 'pddLine'):
      self.calibrationCurveChart.RemovePlotInstance(self.pddLine)
    self.pddLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.LINE)
    self.pddLine.SetInputData(self.pddDataTable, 0, 1)
    self.pddLine.SetColor(0, 0, 255, 255)
    self.pddLine.SetWidth(2.0)

    # Add aligned curve to the graph
    self.calibrationDataAlignedTable = vtk.vtkTable()
    calibrationDataAlignedNumberOfRows = self.logic.calibrationDataAlignedToDisplayArray.shape[0]
    calibrationDataAlignedDepthArray = vtk.vtkDoubleArray()
    calibrationDataAlignedDepthArray.SetName("Depth (cm)")
    self.calibrationDataAlignedTable.AddColumn(calibrationDataAlignedDepthArray)
    calibrationDataAlignedValueArray = vtk.vtkDoubleArray()
    calibrationDataAlignedValueArray.SetName("Aligned calibration data")
    self.calibrationDataAlignedTable.AddColumn(calibrationDataAlignedValueArray)

    self.calibrationDataAlignedTable.SetNumberOfRows(calibrationDataAlignedNumberOfRows)
    for calibrationDataAlignedDepthCounter in range(calibrationDataAlignedNumberOfRows):
      self.calibrationDataAlignedTable.SetValue(calibrationDataAlignedDepthCounter, 0, self.logic.calibrationDataAlignedToDisplayArray[calibrationDataAlignedDepthCounter, 0])
      self.calibrationDataAlignedTable.SetValue(calibrationDataAlignedDepthCounter, 1, self.logic.calibrationDataAlignedToDisplayArray[calibrationDataAlignedDepthCounter, 1])

    if hasattr(self, 'calibrationDataAlignedLine'):
      self.calibrationCurveChart.RemovePlotInstance(self.calibrationDataAlignedLine)
    self.calibrationDataAlignedLine = self.calibrationCurveChart.AddPlot(vtk.vtkChart.LINE)
    self.calibrationDataAlignedLine.SetInputData(self.calibrationDataAlignedTable, 0, 1)
    self.calibrationDataAlignedLine.SetColor(0, 212, 0, 255)
    self.calibrationDataAlignedLine.SetWidth(2.0)

    # Show chart
    self.calibrationCurveChart.GetAxis(1).SetTitle('Depth (cm) - select region using right mouse button to be considered for calibration')
    self.calibrationCurveChart.GetAxis(0).SetTitle('Percent Depth Dose / ΔR1 or ΔR2')
    self.calibrationCurveChart.SetShowLegend(True)
    self.calibrationCurveChart.SetTitle('PDD vs Calibration data')
    self.calibrationCurveChartView.GetInteractor().Initialize()
    self.calibrationCurveChartRenderWindow = self.calibrationCurveChartView.GetRenderWindow()
    self.calibrationCurveChartRenderWindow.SetSize(800,550)
    # To prevent window size from changing
    #if not hasattr(self, "_calibrationCurveChartInitialized"):
      #self._calibrationCurveChartInitialized = True
    self.calibrationCurveChartRenderWindow.SetWindowName('PDD vs Calibration data chart')
    self.calibrationCurveChartRenderWindow.Start()

  #------------------------------------------------------------------------------
  def onAlignCalibrationCurves(self):
    if self.logic.pddDataArray is None or self.logic.pddDataArray.size == 0:
      slicer.util.errorDisplay('PDD data not loaded!')
      return False

    # Parse calibration volume (average ΔR1 or ΔR2 values along central cylinder)
    success = self.parseCalibrationVolume()
    if not success:
      return False

    # Align PDD data and "experimental" (CALIBRATION) data. Allow for horizontal shift
    # and vertical scale (max PDD Y value/max CALIBRATION Y value).
    result = self.logic.alignPddToCalibration()

    # Set alignment results to manual controls
    self.step3_1_xTranslationSpinBox.blockSignals(True)
    self.step3_1_xTranslationSpinBox.setValue(result[1])
    self.step3_1_xTranslationSpinBox.blockSignals(False)
    self.step3_1_yScaleSpinBox.blockSignals(True)
    self.step3_1_yScaleSpinBox.setValue(result[2])
    self.step3_1_yScaleSpinBox.blockSignals(False)
    self.step3_1_yTranslationSpinBox.blockSignals(True)
    self.step3_1_yTranslationSpinBox.setValue(result[3])
    self.step3_1_yTranslationSpinBox.blockSignals(False)

    # Show plots
    self.createCalibrationCurvesWindow()
    self.showCalibrationCurves()

    return True

  #------------------------------------------------------------------------------
  def onAdjustAlignmentValueChanged(self, value):
    self.logic.createAlignedCalibrationArray(self.step3_1_xTranslationSpinBox.value, self.step3_1_yScaleSpinBox.value, self.step3_1_yTranslationSpinBox.value)
    self.showCalibrationCurves()

  #------------------------------------------------------------------------------
  def onToggleCustomLineSampling(self, enabled):
    self.step3_1_calibrationRulerSelector.enabled = enabled
    self.step3_1_lineSamplingRadiusSpinBox.enabled = enabled
    # Disable/enable the standard radius field
    self.step3_1_radiusMmFromCentrePixelLineEdit.enabled = not enabled
    
    # Automatically switch to ruler placement mode when enabled
    if enabled:
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      interactionNode = appLogic.GetInteractionNode()
      
      # Switch to place ruler mode
      interactionNode.SwitchToSinglePlaceMode()
      selectionNode.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsLineNode")
      
      # Connect to ruler selector to observe changes
      self.step3_1_calibrationRulerSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onCalibrationRulerChanged)
      
      # Show calibration volume when enabling custom line sampling
      self.showCalibrationVolumeIn4Up()
    else:
      # Disconnect observer when disabled
      try:
        self.step3_1_calibrationRulerSelector.disconnect("currentNodeChanged(vtkMRMLNode*)", self.onCalibrationRulerChanged)
      except:
        pass
      # Remove observer from current ruler if it exists
      if hasattr(self, 'calibrationRulerObserverTag') and self.calibrationRulerObserverTag is not None:
        rulerNode = self.step3_1_calibrationRulerSelector.currentNode()
        if rulerNode:
          rulerNode.RemoveObserver(self.calibrationRulerObserverTag)
        self.calibrationRulerObserverTag = None
  
  #------------------------------------------------------------------------------
  def onCalibrationRulerChanged(self, rulerNode):
    # Remove observer from previous ruler
    if hasattr(self, 'calibrationRulerObserverTag') and self.calibrationRulerObserverTag is not None:
      if hasattr(self, 'previousCalibrationRuler') and self.previousCalibrationRuler:
        self.previousCalibrationRuler.RemoveObserver(self.calibrationRulerObserverTag)
      self.calibrationRulerObserverTag = None
    
    # Add observer to new ruler
    if rulerNode:
      if rulerNode.GetNumberOfControlPoints() == 0:
        appLogic = slicer.app.applicationLogic()
        interactionNode = appLogic.GetInteractionNode()
        selectionNode = appLogic.GetSelectionNode()
        selectionNode.SetActivePlaceNodeID(rulerNode.GetID())
        interactionNode.SetCurrentInteractionMode(interactionNode.Place)
      
      # Observe when the ruler is modified
      self.calibrationRulerObserverTag = rulerNode.AddObserver(slicer.vtkMRMLMarkupsNode.PointModifiedEvent, self.onCalibrationRulerMoved)
      self.previousCalibrationRuler = rulerNode
      
      # Show calibration volume in 4-Up view
      self.showCalibrationVolumeIn4Up()
      
      # Update the plot immediately with the new ruler
      if self.logic.pddDataArray is not None and self.logic.pddDataArray.size > 0:
        self.updateCalibrationWithCustomLine()
  
  #------------------------------------------------------------------------------
  def showCalibrationVolumeIn4Up(self):
    # Display calibration volume in 4-up view
    calibrationVolume = self.calibrationVolumeNode
    
    # Switch to 4-up view
    layoutManager = slicer.app.layoutManager()
    layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    
    # Set calibration volume as background in all views
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(calibrationVolume.GetID())
    appLogic.PropagateVolumeSelection()
    
    # Reset field of view in all slice views
    layoutManager = self.layoutWidget.layoutManager()
    threeDWidget = layoutManager.threeDWidget(0)
    if threeDWidget is not None and threeDWidget.threeDView() is not None:
      threeDWidget.threeDView().resetFocalPoint()
    
  #------------------------------------------------------------------------------
  def onCalibrationRulerMoved(self, caller, event):
    # Only update if we have PDD data already loaded
    if self.logic.pddDataArray is not None and self.logic.pddDataArray.size > 0:
      self.updateCalibrationWithCustomLine()

  #------------------------------------------------------------------------------
  def updateCalibrationWithCustomLine(self):
  # Update the calibration curve using the current ruler position
    if not self.step3_1_useCustomLineSampling.isChecked():
      return
    
    rulerNode = self.step3_1_calibrationRulerSelector.currentNode()
    if not rulerNode or not self.calibrationVolumeNode:
      return
    
    if rulerNode.GetNumberOfControlPoints() < 2:
      return 

    if self.logic.pddDataArray is None or self.logic.pddDataArray.size == 0:
      return  

    if not hasattr(self, 'calibrationCurveChart'):
      return 
    
    # Sample along the line
    samplingRadius = self.step3_1_lineSamplingRadiusSpinBox.value
    success = self.logic.sampleCalibrationAlongLine(self.calibrationVolumeNode, rulerNode, samplingRadius)
    
    if success:
      result = self.logic.alignPddToCalibration()
      
      # Update manual controls
      self.step3_1_xTranslationSpinBox.blockSignals(True)
      self.step3_1_xTranslationSpinBox.setValue(result[1])
      self.step3_1_xTranslationSpinBox.blockSignals(False)
      self.step3_1_yScaleSpinBox.blockSignals(True)
      self.step3_1_yScaleSpinBox.setValue(result[2])
      self.step3_1_yScaleSpinBox.blockSignals(False)
      self.step3_1_yTranslationSpinBox.blockSignals(True)
      self.step3_1_yTranslationSpinBox.setValue(result[3])
      self.step3_1_yTranslationSpinBox.blockSignals(False)
      
      # Update the plot
      self.showCalibrationCurves()
 
  #------------------------------------------------------------------------------
  def onLineSamplingRadiusChanged(self, value):
    if self.step3_1_useCustomLineSampling.isChecked():
      self.updateCalibrationWithCustomLine()

  #------------------------------------------------------------------------------
  def onComputeDoseFromPdd(self):
    try:
      monitorUnitsFloat = float(self.step3_1_monitorUnitsLineEdit.text)
      rdfFloat = float(self.step3_1_rdfLineEdit.text)
    except ValueError:
      slicer.util.errorDisplay('Invalid monitor units or RDF!')
      return False

    # Calculate dose information: calculatedDose = (PddDose * MonitorUnits * RDF) / 10000
    if self.logic.computeDoseForMeasuredData(rdfFloat, monitorUnitsFloat) == False:
      qt.QMessageBox.critical(None, "Error", 'Dose calculation from PDD failed!')
      return False

    qt.QMessageBox.information(None, "Success", "Dose successfully calculated from PDD.")
    return True

  #------------------------------------------------------------------------------
  def onShowDeltaRVsDoseCurve(self):
    # Get selection from PDD vs Calibration chart
    selection = self.pddLine.GetSelection()
    if selection is not None and selection.GetNumberOfTuples() > 0:
      pddRangeMin = self.pddDataTable.GetValue(selection.GetValue(0), 0)
      pddRangeMax = self.pddDataTable.GetValue(selection.GetValue(selection.GetNumberOfTuples()-1), 0)
    else:
      pddRangeMin = -1000
      pddRangeMax = 1000
    logging.info('Selected Pdd range: {0} - {1}'.format(pddRangeMin,pddRangeMax))

    # Create ΔR1 or ΔR2 vs dose function
    self.logic.createDeltaRVsDoseFunction(pddRangeMin, pddRangeMax)

    self.deltaRVsDoseChartView = vtk.vtkContextView()
    self.deltaRVsDoseChartView.GetRenderer().SetBackground(1,1,1)
    self.deltaRVsDoseChart = vtk.vtkChartXY()
    self.deltaRVsDoseChartView.GetScene().AddItem(self.deltaRVsDoseChart)

    # Create ΔR1 or ΔR2 vs dose plot
    self.deltaRVsDoseDataTable = vtk.vtkTable()
    deltaRVsDoseNumberOfRows = self.logic.deltaRVsDoseFunction.shape[0]

    deltaRArray = vtk.vtkDoubleArray()
    deltaRArray.SetName("ΔR1 or ΔR2 (s^-1)")
    self.deltaRVsDoseDataTable.AddColumn(deltaRArray)
    doseArray = vtk.vtkDoubleArray()
    doseArray.SetName("Dose (GY)")
    self.deltaRVsDoseDataTable.AddColumn(doseArray)

    self.deltaRVsDoseDataTable.SetNumberOfRows(deltaRVsDoseNumberOfRows)
    for rowIndex in range(deltaRVsDoseNumberOfRows):
      self.deltaRVsDoseDataTable.SetValue(rowIndex, 0, self.logic.deltaRVsDoseFunction[rowIndex, 0])
      self.deltaRVsDoseDataTable.SetValue(rowIndex, 1, self.logic.deltaRVsDoseFunction[rowIndex, 1])

    self.deltaRVsDoseLinePoint = self.deltaRVsDoseChart.AddPlot(vtk.vtkChart.POINTS)
    self.deltaRVsDoseLinePoint.SetInputData(self.deltaRVsDoseDataTable, 0, 1)
    self.deltaRVsDoseLinePoint.SetColor(0, 0, 255, 255)
    self.deltaRVsDoseLinePoint.SetMarkerSize(10)
    self.deltaRVsDoseLineInnerPoint = self.deltaRVsDoseChart.AddPlot(vtk.vtkChart.POINTS)
    self.deltaRVsDoseLineInnerPoint.SetInputData(self.deltaRVsDoseDataTable, 0, 1)
    self.deltaRVsDoseLineInnerPoint.SetColor(255, 255, 255, 223)
    self.deltaRVsDoseLineInnerPoint.SetMarkerSize(8)

    # Show chart
    self.deltaRVsDoseChart.GetAxis(1).SetTitle('ΔR1 or ΔR2 (s^-1)')
    self.deltaRVsDoseChart.GetAxis(0).SetTitle('Dose (GY)')
    self.deltaRVsDoseChart.SetTitle('ΔR1 or ΔR2 vs Dose')
    self.deltaRVsDoseChartView.GetInteractor().Initialize()
    self.deltaRVsDoseChartRenderWindow = self.deltaRVsDoseChartView.GetRenderWindow()
    self.deltaRVsDoseChartRenderWindow.SetSize(800,550)
    self.deltaRVsDoseChartRenderWindow.SetWindowName('Delta R1 or Delta R2 vs Dose chart')
    self.deltaRVsDoseChartRenderWindow.Start()

  #------------------------------------------------------------------------------
  def onRemoveSelectedPointsFromDeltaRVsDoseCurve(self):
    outlierSelection = None
    if hasattr(self, 'deltaRVsDoseLineInnerPoint') and self.deltaRVsDoseLineInnerPoint:
      outlierSelection = self.deltaRVsDoseLineInnerPoint.GetSelection()
    if outlierSelection is None and hasattr(self, 'deltaRVsDoseLinePoint') and self.deltaRVsDoseLinePoint:
      outlierSelection = self.deltaRVsDoseLinePoint.GetSelection()
    if outlierSelection is None:
      qt.QMessageBox.information(None, "ΔR1 or ΔR2 vs Dose", "Please right-click the points you want to remove on the ΔR1 or ΔR2 vs. Dose chart.")
      return
    
    if outlierSelection is not None and outlierSelection.GetNumberOfTuples() > 0:
      # Get outlier indices in descending order
      outlierIndices = []
      for outlierSelectionIndex in range(outlierSelection.GetNumberOfTuples()):
        outlierIndex = outlierSelection.GetValue(outlierSelectionIndex)
        outlierIndices.append(outlierIndex)
      outlierIndices.sort()
      outlierIndices.reverse()
      for outlierIndex in outlierIndices:
        self.deltaRVsDoseDataTable.RemoveRow(outlierIndex)
        self.logic.deltaRVsDoseFunction = numpy.delete(self.logic.deltaRVsDoseFunction, outlierIndex, 0)

      # De-select former points
      emptySelectionArray = vtk.vtkIdTypeArray()
      if hasattr(self, 'deltaRVsDoseLinePoint') and self.deltaRVsDoseLinePoint:
        self.deltaRVsDoseLinePoint.SetSelection(emptySelectionArray)
      if hasattr(self, 'deltaRVsDoseLineInnerPoint') and self.deltaRVsDoseLineInnerPoint:
        self.deltaRVsDoseLineInnerPoint.SetSelection(emptySelectionArray)
      if hasattr(self, 'polynomialLine') and self.polynomialLine is not None:
        self.polynomialLine.SetSelection(emptySelectionArray)
      # Update chart view
      self.deltaRVsDoseDataTable.Modified()
      self.deltaRVsDoseChartView.Render()

  #------------------------------------------------------------------------------
  def onFitPolynomialToDeltaRVsDoseCurve(self):
    orderSelectionComboboxCurrentIndex = self.step3_1_selectOrderOfPolynomialFitButton.currentIndex
    maxOrder = int(self.step3_1_selectOrderOfPolynomialFitButton.itemText(orderSelectionComboboxCurrentIndex))
    residuals = self.logic.fitCurveToDeltaRVsDoseFunctionArray(maxOrder)
    p = self.logic.calibrationPolynomialCoefficients

    # Clear line edits
    for order in range(5):
      self.step3_2_calibrationFunctionOrderLineEdits[order].text = ''
    # Show polynomial on GUI (highest order first in the coefficients list)
    for orderIndex in range(maxOrder+1):
      order = maxOrder-orderIndex
      self.step3_2_calibrationFunctionOrderLineEdits[order].text = '{1:.6f}'.format(order,p[orderIndex])
    # Show residuals
    self.step3_1_fitPolynomialResidualsLabel.text = "Residuals of the least-squares fit of the polynomial: {0:.3f}".format(residuals[0])

    # Compute points to display for the fitted polynomial
    deltaRVsDoseNumberOfRows = self.logic.deltaRVsDoseFunction.shape[0]
    minDeltaR = self.logic.deltaRVsDoseFunction[0, 0]
    maxDeltaR = self.logic.deltaRVsDoseFunction[deltaRVsDoseNumberOfRows-1, 0]
    minPolynomial = minDeltaR - (maxDeltaR-minDeltaR)*0.2
    maxPolynomial = maxDeltaR + (maxDeltaR-minDeltaR)*0.2

    # Create table to display polynomial
    self.polynomialTable = vtk.vtkTable()
    polynomialXArray = vtk.vtkDoubleArray()
    polynomialXArray.SetName("X")
    self.polynomialTable.AddColumn(polynomialXArray)
    polynomialYArray = vtk.vtkDoubleArray()
    polynomialYArray.SetName("Y")
    self.polynomialTable.AddColumn(polynomialYArray)
    # The displayed polynomial is 4 times as dense as the ΔR1 or ΔR2 VS dose curve
    polynomialNumberOfRows = deltaRVsDoseNumberOfRows * 4
    self.polynomialTable.SetNumberOfRows(polynomialNumberOfRows)
    for rowIndex in range(polynomialNumberOfRows):
      x = minPolynomial + (maxPolynomial-minPolynomial)*rowIndex/polynomialNumberOfRows
      self.polynomialTable.SetValue(rowIndex, 0, x)
      y = 0
      # Highest order first in the coefficients list
      for orderIndex in range(maxOrder+1):
        y += p[orderIndex] * x ** (maxOrder-orderIndex)
      self.polynomialTable.SetValue(rowIndex, 1, y)

    if hasattr(self, 'polynomialLine') and self.polynomialLine is not None:
      self.deltaRVsDoseChart.RemovePlotInstance(self.polynomialLine)

    self.polynomialLine = self.deltaRVsDoseChart.AddPlot(vtk.vtkChart.LINE)
    self.polynomialLine.SetInputData(self.polynomialTable, 0, 1)
    self.polynomialLine.SetColor(192, 0, 0, 255)
    self.polynomialLine.SetWidth(2)

  #------------------------------------------------------------------------------
  def setCalibrationFunctionCoefficientsToLogic(self):
    # Determine the number of orders based on the input fields
    maxOrder = 0
    for order in range(5):
      lineEditText = self.step3_2_calibrationFunctionOrderLineEdits[order].text
      try:
        coefficient = float(lineEditText)
        if coefficient != 0:
          maxOrder = order
      except:
        pass
    # Initialize all coefficients to zero in the coefficients list
    self.logic.calibrationPolynomialCoefficients = numpy.zeros(maxOrder+1)
    for order in range(maxOrder+1):
      lineEditText = self.step3_2_calibrationFunctionOrderLineEdits[order].text
      try:
        self.logic.calibrationPolynomialCoefficients[maxOrder-order] = float(lineEditText)
      except:
        pass
    logging.info('Manual calibration coefficients applied (highest order first): ' + repr(self.logic.calibrationPolynomialCoefficients.tolist()))

  #------------------------------------------------------------------------------
  def onExportCalibration(self):
    # Set calibration polynomial coefficients from input fields to logic
    self.setCalibrationFunctionCoefficientsToLogic()

    # Export
    result = self.logic.exportCalibrationToCSV()
    qt.QMessageBox.information(None, 'Calibration values exported', result)

  #------------------------------------------------------------------------------
  def onApplyCalibration(self):
    # Set calibration polynomial coefficients from input fields to logic if entered manually
    if self.logic.calibrationPolynomialCoefficients is None:
      self.setCalibrationFunctionCoefficientsToLogic()

    # Perform calibration
    self.calibratedMeasuredVolumeNode = self.logic.calibrate(self.measuredVolumeNode.GetID())
    if self.calibratedMeasuredVolumeNode is not None:
      self.step3_2_applyCalibrationStatusLabel.setText('Calibration successfully performed')
    else:
      self.step3_2_applyCalibrationStatusLabel.setText('Calibration failed!')
      return False

    # Show calibrated volume
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(self.planDoseVolumeNode.GetID())
    selectionNode.SetSecondaryVolumeID(self.calibratedMeasuredVolumeNode.GetID())
    appLogic.PropagateVolumeSelection()

    # Set window/level options for the calibrated dose
    if self.logic.deltaRVsDoseFunction is not None:
      calibratedVolumeDisplayNode = self.calibratedMeasuredVolumeNode.GetDisplayNode()
      deltaRVsDoseNumberOfRows = self.logic.deltaRVsDoseFunction.shape[0]
      minDose = self.logic.deltaRVsDoseFunction[0, 1]
      maxDose = self.logic.deltaRVsDoseFunction[deltaRVsDoseNumberOfRows-1, 1]
      minWindowLevel = minDose - (maxDose-minDose)*0.2
      maxWindowLevel = maxDose + (maxDose-minDose)*0.2
      calibratedVolumeDisplayNode.AutoWindowLevelOff()
      calibratedVolumeDisplayNode.SetWindowLevelMinMax(minWindowLevel, maxWindowLevel)

    # Set calibrated dose to dose comparison step input
    self.refreshDoseComparisonInfoLabel()
    return True

  #------------------------------------------------------------------------------
  # Step 4
  #------------------------------------------------------------------------------
  def refreshDoseComparisonInfoLabel(self):
    if self.planDoseVolumeNode is None:
      self.step4_doseComparisonReferenceVolumeLabel.text = 'Invalid plan dose volume!'
    else:
      self.step4_doseComparisonReferenceVolumeLabel.text = self.planDoseVolumeNode.GetName()
    if self.calibratedMeasuredVolumeNode is None:
      self.step4_doseComparisonEvaluatedVolumeLabel.text = 'Invalid calibrated gel dosimeter volume!'
    else:
      self.step4_doseComparisonEvaluatedVolumeLabel.text = self.calibratedMeasuredVolumeNode.GetName()

  #------------------------------------------------------------------------------
  def onStep4_DoseComparisonSelected(self, collapsed):
    # Initialize mask segmentation selector to select plan structures
    self.step4_maskSegmentationSelector.setCurrentNode(self.planStructuresNode)
    self.onStep4_MaskSegmentationSelectionChanged(self.planStructuresNode)
    # Turn scalar bar on/off
    if collapsed == False:
      self.sliceAnnotations.scalarBarEnabled = 1
    else:
      self.sliceAnnotations.scalarBarEnabled = 0
    self.sliceAnnotations.updateSliceViewFromGUI()
    # Reset 3D view
    self.layoutWidget.layoutManager().threeDWidget(0).threeDView().resetFocalPoint()

  #------------------------------------------------------------------------------
  def onStep4_MaskSegmentationSelectionChanged(self, node):
    # Hide previously selected mask segmentation
    if self.maskSegmentationNode is not None:
      self.maskSegmentationNode.GetDisplayNode().SetVisibility(0)
    # Set new mask segmentation
    self.maskSegmentationNode = node
    self.onStep4_MaskSegmentSelectionChanged(self.step4_maskSegmentationSelector.currentSegmentID())
    # Show new mask segmentation
    if self.maskSegmentationNode is not None:
      self.maskSegmentationNode.GetDisplayNode().SetVisibility(1)
  
  #------------------------------------------------------------------------------
  def onStep4_MaskSegmentSelectionChanged(self, segmentID):
    if self.maskSegmentationNode is None:
      return
    # Set new mask segment
    self.maskSegmentID = segmentID

    # Hide all other segments
    import vtkSegmentationCorePython as vtkSegmentationCore
    segmentIDs = vtk.vtkStringArray()
    self.maskSegmentationNode.GetSegmentation().GetSegmentIDs(segmentIDs)
    for segmentIndex in range(0,segmentIDs.GetNumberOfValues()):
      currentSegmentID = segmentIDs.GetValue(segmentIndex)
      self.maskSegmentationNode.GetDisplayNode().SetSegmentVisibility(currentSegmentID, False)
    # Show only selected segment, make it semi-transparent
    if self.maskSegmentID is not None and self.maskSegmentID != '':
      self.maskSegmentationNode.GetDisplayNode().SetSegmentVisibility(self.maskSegmentID, True)
      self.maskSegmentationNode.GetDisplayNode().SetSegmentOpacity3D(self.maskSegmentID, 0.5)
  
  #------------------------------------------------------------------------------
  def onUseMaximumDoseRadioButtonToggled(self, toggled):
    self.step4_1_referenceDoseCustomValueCGySpinBox.setEnabled(not toggled)

  #------------------------------------------------------------------------------
  def onGammaDoseComparison(self):
    try:
      slicer.modules.dosecomparison

      if self.step4_1_gammaVolumeSelector.currentNode() is None:
        qt.QMessageBox.warning(None, 'Warning', 'Gamma volume not selected. If there is no suitable output gamma volume, create one.')
        return False
      else:
        self.gammaVolumeNode = self.step4_1_gammaVolumeSelector.currentNode()

      # Set up gamma computation parameters
      self.gammaParameterSetNode = slicer.vtkMRMLDoseComparisonNode()
      slicer.mrmlScene.AddNode(self.gammaParameterSetNode)
      self.gammaParameterSetNode.SetAndObserveReferenceDoseVolumeNode(self.planDoseVolumeNode)
      self.gammaParameterSetNode.SetAndObserveCompareDoseVolumeNode(self.calibratedMeasuredVolumeNode)
      # Ensure binary labelmap representation exists for gamma mask
      if self.maskSegmentationNode is not None and self.maskSegmentID:
          segmentation = self.maskSegmentationNode.GetSegmentation()
          if not segmentation.ContainsRepresentation(
                  slicer.vtkSegmentationConverter.GetBinaryLabelmapRepresentationName()):
              segmentation.CreateRepresentation(
                  slicer.vtkSegmentationConverter.GetBinaryLabelmapRepresentationName())
      self.gammaParameterSetNode.SetAndObserveMaskSegmentationNode(self.maskSegmentationNode)
      if self.maskSegmentID is not None and self.maskSegmentID != '':
        self.gammaParameterSetNode.SetMaskSegmentID(self.maskSegmentID)
      else:
        self.gammaParameterSetNode.SetMaskSegmentID(None)
      self.gammaParameterSetNode.SetAndObserveGammaVolumeNode(self.gammaVolumeNode)
      self.gammaParameterSetNode.SetDtaDistanceToleranceMm(self.step4_1_dtaDistanceToleranceMmSpinBox.value)
      self.gammaParameterSetNode.SetDoseDifferenceTolerancePercent(self.step4_1_doseDifferenceTolerancePercentSpinBox.value)
      self.gammaParameterSetNode.SetUseMaximumDose(self.step4_1_referenceDoseUseMaximumDoseRadioButton.isChecked())
      self.gammaParameterSetNode.SetUseGeometricGammaCalculation(self.step4_1_useGeometricGammaCalculation.isChecked())
      self.gammaParameterSetNode.SetReferenceDoseGy(self.step4_1_referenceDoseCustomValueCGySpinBox.value / 100.0)
      self.gammaParameterSetNode.SetAnalysisThresholdPercent(self.step4_1_analysisThresholdPercentSpinBox.value)
      self.gammaParameterSetNode.SetDoseThresholdOnReferenceOnly(True)
      self.gammaParameterSetNode.SetMaximumGamma(self.step4_1_maximumGammaSpinBox.value)

      # Create progress bar
      doseComparisonLogic = slicer.modules.dosecomparison.logic()
      self.addObserver(doseComparisonLogic, 62200, self.onGammaProgressUpdated) # Note: Event number defined in SlicerRtCommon.ProgressUpdated, but python wrapping does not work anymore for SlicerRtCommon
      self.gammaProgressDialog = qt.QProgressDialog(self.parent)
      self.gammaProgressDialog.setModal(True)
      self.gammaProgressDialog.setMinimumDuration(150)
      self.gammaProgressDialog.labelText = "Computing gamma dose difference..."
      self.gammaProgressDialog.show()
      slicer.app.processEvents()

      # Perform gamma comparison
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      errorMessage = doseComparisonLogic.ComputeGammaDoseDifference(self.gammaParameterSetNode)

      self.gammaProgressDialog.hide()
      self.gammaProgressDialog = None
      self.removeObserver(doseComparisonLogic, 62200, self.onGammaProgressUpdated)
      qt.QApplication.restoreOverrideCursor()

      if self.gammaParameterSetNode.GetResultsValid():
        self.step4_1_gammaStatusLabel.setText('Gamma dose comparison succeeded\nPass fraction: {0:.2f}%'.format(self.gammaParameterSetNode.GetPassFractionPercent()))
        self.step4_1_showGammaReportButton.enabled = True
        self.gammaReport = self.gammaParameterSetNode.GetReportString()
      else:
        self.step4_1_gammaStatusLabel.setText(errorMessage)
        self.step4_1_showGammaReportButton.enabled = False

      # Show gamma volume
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      selectionNode.SetActiveVolumeID(self.gammaVolumeNode.GetID())
      selectionNode.SetSecondaryVolumeID(None)
      appLogic.PropagateVolumeSelection()

      # Show mask structure with some transparency
      if self.maskSegmentationNode:
        self.maskSegmentationNode.GetDisplayNode().SetVisibility(1)
        if self.maskSegmentID:
          self.maskSegmentationNode.GetDisplayNode().SetSegmentVisibility(self.maskSegmentID, True)
          self.maskSegmentationNode.GetDisplayNode().SetSegmentOpacity3D(self.maskSegmentID, 0.5)

      # Show gamma slice in 3D view
      layoutManager = self.layoutWidget.layoutManager()
      sliceViewerWidgetRed = layoutManager.sliceWidget('Red')
      sliceLogicRed = sliceViewerWidgetRed.sliceLogic()
      sliceLogicRed.StartSliceNodeInteraction(slicer.vtkMRMLSliceNode.SliceVisibleFlag)
      sliceLogicRed.GetSliceNode().SetSliceVisible(1)
      sliceLogicRed.EndSliceNodeInteraction()

      # Set gamma window/level
      maximumGamma = self.step4_1_maximumGammaSpinBox.value
      gammaDisplayNode = self.gammaVolumeNode.GetDisplayNode()
      if gammaDisplayNode is None:
        self.gammaVolumeNode.CreateDefaultDisplayNodes()
        gammaDisplayNode = self.gammaVolumeNode.GetDisplayNode()
      gammaDisplayNode.AutoWindowLevelOff()
      gammaDisplayNode.SetWindowLevel(maximumGamma/2, maximumGamma/2)
      gammaDisplayNode.ApplyThresholdOn()
      gammaDisplayNode.AutoThresholdOff()
      gammaDisplayNode.SetLowerThreshold(0.001)

      # Center 3D view
      layoutManager = self.layoutWidget.layoutManager()
      threeDWidget = layoutManager.threeDWidget(0)
      if threeDWidget is not None and threeDWidget.threeDView() is not None:
        threeDWidget.threeDView().resetFocalPoint()

      return True

    except Exception as e:
      import traceback
      traceback.print_exc()
      logging.error('Failed to perform gamma dose comparison!')

  #------------------------------------------------------------------------------
  def onGammaProgressUpdated(self, logic, event):
    if self.gammaProgressDialog:
      self.gammaProgressDialog.value = logic.GetProgress() * 100.0
      slicer.app.processEvents()

  #------------------------------------------------------------------------------
  def onShowGammaReport(self):
    if hasattr(self,"gammaReport"):
      qt.QMessageBox.information(None, 'Gamma computation report', self.gammaReport)
    else:
      qt.QMessageBox.information(None, 'Gamma computation report missing', 'No report available!')

  #------------------------------------------------------------------------------
  # Step T1
  #------------------------------------------------------------------------------
  def onStepT1_LineProfileSelected(self, collapsed):
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    interactionNode = appLogic.GetInteractionNode()

    # Change to quantitative view on enter, change back on leave
    if collapsed == False:
      self.currentLayoutIndex = self.step0_viewSelectorComboBox.currentIndex
      self.onViewSelect(5)

      # Switch to place ruler mode
      interactionNode.SwitchToSinglePlaceMode()
      selectionNode.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsLineNode")
    else:
      self.onViewSelect(self.currentLayoutIndex)

    # Show dose volumes
    if self.planDoseVolumeNode:
      selectionNode.SetActiveVolumeID(self.planDoseVolumeNode.GetID())
    if self.calibratedMeasuredVolumeNode:
      selectionNode.SetSecondaryVolumeID(self.calibratedMeasuredVolumeNode.GetID())
    appLogic = slicer.app.applicationLogic()
    appLogic.PropagateVolumeSelection()

  #------------------------------------------------------------------------------
  def onCreateLineProfileButton(self):
    # Create table nodes for the results
    if not hasattr(self, 'lineProfileTableNode'):
      self.lineProfileTableNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode")

    # Set up line profile logic
    self.lineProfileLogic.outputPlotSeriesNodes = {}
    self.lineProfileLogic.outputTableNode = self.lineProfileTableNode
    self.lineProfileLogic.inputRulerNode = self.stepT1_inputRulerSelector.currentNode()
    self.lineProfileLogic.enableAutoUpdate(True)

    rulerLengthMm = self.lineProfileLogic.computeRulerLength(self.lineProfileLogic.inputRulerNode)
    lineResolutionMm = float(self.stepT1_lineResolutionMmSliderWidget.value)
    self.lineProfileLogic.lineResolution = int( (rulerLengthMm / lineResolutionMm) + 0.5 )

    # Get number of samples based on selected sampling density
    self.lineProfileLogic.inputVolumeNodes = []
    if self.planDoseVolumeNode:
      self.lineProfileLogic.inputVolumeNodes.append(self.planDoseVolumeNode)
      if not hasattr(self, 'planDosePlotSeriesNode'):
        self.planDosePlotSeriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode")
      self.lineProfileLogic.outputPlotSeriesNodes[self.planDoseVolumeNode.GetID()] = self.planDosePlotSeriesNode
    if self.calibratedMeasuredVolumeNode:
      self.lineProfileLogic.inputVolumeNodes.append(self.calibratedMeasuredVolumeNode)
      if not hasattr(self, 'calibratedMeasuredPlotSeriesNode'):
        self.calibratedMeasuredPlotSeriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode")
      self.lineProfileLogic.outputPlotSeriesNodes[self.calibratedMeasuredVolumeNode.GetID()] = self.calibratedMeasuredPlotSeriesNode
    if self.gammaVolumeNode:
      self.lineProfileLogic.inputVolumeNodes.append(self.gammaVolumeNode)
      if not hasattr(self, 'gammaPlotSeriesNode'):
        self.gammaPlotSeriesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode")
      self.lineProfileLogic.outputPlotSeriesNodes[self.gammaVolumeNode.GetID()] = self.gammaPlotSeriesNode

    # Line profile plot
    self.lineProfileLogic.update()
    if getattr(self, 'planDosePlotSeriesNode', None):
        self.planDosePlotSeriesNode.SetName("Planned Dose")
    if getattr(self, 'calibratedMeasuredPlotSeriesNode', None):
        self.calibratedMeasuredPlotSeriesNode.SetName("Calibrated Measured Dose")
    if getattr(self, 'gammaPlotSeriesNode', None):
        self.gammaPlotSeriesNode.SetName("Gamma Volume")
    
    pcn = self.lineProfileLogic.plotChartNode
    if pcn:
      if hasattr(pcn, "SetShowLegend"):
        pcn.SetShowLegend(True)
      elif hasattr(pcn, "SetLegendVisibility"):
        pcn.SetLegendVisibility(True)

    # Build exportable [Distance(mm), Value] rows from the table
    table = self.lineProfileTableNode.GetTable()
    if not table or table.GetNumberOfRows() == 0:
        self.lineProfileData = None
        return
    n = table.GetNumberOfRows()
    self.lineProfileData = [[table.GetValue(i, 0), table.GetValue(i, 1)] for i in range(n)]

  #------------------------------------------------------------------------------
  def onLegendVisibilityToggled(self, on):
    if self.lineProfileLogic.plotChartNode is None:
      message = 'Need to create line profile first'
      logging.error(message)
      qt.QMessageBox.critical(None, 'Error', message)
      return

    self.lineProfileLogic.plotChartNode.SetLegendVisibility(on)

  #------------------------------------------------------------------------------
  def onSelectLineProfileParameters(self):
    self.stepT1_createLineProfileButton.enabled = self.planDoseVolumeNode and self.measuredVolumeNode and self.stepT1_inputRulerSelector.currentNode()

  #------------------------------------------------------------------------------
  def onExportLineProfiles(self):
    if hasattr(self, "lineProfileData") and self.lineProfileData is not None:
      self.logic.exportLineProfileToCSV(self.lineProfileData)
    else:
      slicer.util.delayDisplay("No line profile available to export.")

  #------------------------------------------------------------------------------
  # STEP 1.2.1
  #------------------------------------------------------------------------------
  def onPreScanSelected(self, node):
    # Enable Delta R workflow when pre-irradiation volume is selected
    if node:
      self.step1_2_1_1_step2_registrationButton.visible = True
      self.step1_2_1_1_step2_registrationButton.enabled = True
      self.step1_2_1_1_step2_registrationButton.collapsed = False
      self.step1_2_1_1_step3_denoisingButton.visible = True
      self.step1_2_1_1_step4_computeButton.visible = True
    else:
      for btn in [self.step1_2_1_1_step2_registrationButton,
                  self.step1_2_1_1_step3_denoisingButton,
                  self.step1_2_1_1_step4_computeButton]:
        btn.enabled = True
        btn.collapsed = True
        btn.visible = False
      
  #------------------------------------------------------------------------------
  def onPostScanSelected(self, node):
    # Auto-populate measured volume when post-irradiation volume is selected
    if node:
      # Set post-irradiation volume as the default measured volume
      self.measuredVolumeNode = node

  #------------------------------------------------------------------------------
  def onStep1_2_Collapsed(self, collapsed):
    # Auto-expand 1.2.1
    if not collapsed:
      self.step1_2_1_measuredGelCollapsibleButton.collapsed = False 

  #------------------------------------------------------------------------------
  def onRegisterPrePost(self):
    # Register post- to pre-irradiation volume using BRAINS
    preScanNode = self.step1_2_1_preScanSelector.currentNode()
    postScanNode = self.step1_2_1_postScanSelector.currentNode()
    
    if not preScanNode or not postScanNode:
      qt.QMessageBox.warning(None, 'Warning', 'Please select both pre and post-irradiation volumes')
      return
    
    try:
      # Create transform node
      transformNode = slicer.mrmlScene.GetFirstNodeByName("PreToPostTransform")
      # Reuse existing transform node if present, otherwise create one
      if transformNode is None:
          transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "PreToPostTransform")
      
      # Set up BRAINS registration parameters
      parameters = {
        "fixedVolume": preScanNode.GetID(),
        "movingVolume": postScanNode.GetID(),
        "linearTransform": transformNode.GetID(),
        "samplingPercentage": 0.02,
        "initializeTransformMode": "useMomentsAlign",
        "useRigid": True
      }
      
      # Run BRAINS registration
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      progressDialog = qt.QProgressDialog("Performing registration. This may take several seconds.", "OK", 0, 0)
      progressDialog.setModal(True)
      progressDialog.setMinimumDuration(0)
      progressDialog.show()
      slicer.app.processEvents()
      
      cliNode = slicer.cli.run(slicer.modules.brainsfit, None, parameters, wait_for_completion=True)
      
      if cliNode.GetStatus() & cliNode.Completed:
        # Create output node for registered post volume
        outputName = postScanNode.GetName() + "_registered"
        outputNode = slicer.mrmlScene.GetFirstNodeByName(outputName)
        if outputNode is None:
          outputNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", outputName)

        resampleParameters = {
          "inputVolume": postScanNode.GetID(),
          "referenceVolume": preScanNode.GetID(),
          "outputVolume": outputNode.GetID(),
          "pixelType": "float",
          "warpTransform": transformNode.GetID(),
          "interpolationMode": "Linear"
        }
        
        cliNode2 = slicer.cli.run(slicer.modules.brainsresample, None, resampleParameters, wait_for_completion=True)
        
        progressDialog.close()
        qt.QApplication.restoreOverrideCursor()
        
        if cliNode2.GetStatus() & cliNode2.Completed:
          self.registeredPostNode = outputNode
          self.transformNode = transformNode
          
          # Enable Steps 3 and 4
          self.step1_2_1_1_step3_denoisingButton.enabled = True
          self.step1_2_1_1_step4_computeButton.enabled = True
          self.step1_2_1_1_computeDeltaRButton.enabled = True
          self.step1_2_1_1_useGRECheckBox.enabled = True

          # Set default denoising input to pre-irradiation volume
          self.step1_2_1_1_denoisingInputSelector.setCurrentNode(preScanNode)

          # Show registered result
          self.showRegistrationResult(preScanNode, outputNode)

          # Create separate manual adjustment transform
          self.manualTransformNode = slicer.mrmlScene.GetFirstNodeByName("PreToPostManualAdjust")
          if self.manualTransformNode is None:
              self.manualTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "PreToPostManualAdjust")
          else:
            matrix = vtk.vtkMatrix4x4()
            self.manualTransformNode.GetMatrixTransformToParent(matrix)
            matrix.Identity()
            self.manualTransformNode.SetMatrixTransformToParent(matrix)
          outputNode.SetAndObserveTransformNodeID(self.manualTransformNode.GetID())
          self.step1_2_1_1_translationSliders.setMRMLTransformNode(self.manualTransformNode)
          self.step1_2_1_1_rotationSliders.setMRMLTransformNode(self.manualTransformNode)
          self.step1_2_1_1_resampleButton.visible = False
        else:
          qt.QMessageBox.critical(None, 'Error', 'Resampling failed')
      else:
        progressDialog.close()
        qt.QApplication.restoreOverrideCursor()
        qt.QMessageBox.critical(None, 'Error', 'Registration failed')
        slicer.mrmlScene.RemoveNode(transformNode)
        
    except Exception as e:
      qt.QApplication.restoreOverrideCursor()
      import traceback
      traceback.print_exc()
      qt.QMessageBox.critical(None, 'Error', f'Registration failed: {str(e)}')

  #------------------------------------------------------------------------------
  def showRegistrationResult(self, fixedVolume, registeredVolume):
    # Display registration result in 4-up view
    layoutManager = slicer.app.layoutManager()
    layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    
    displayNode = registeredVolume.GetDisplayNode()
    if displayNode:
        colorNode = slicer.util.getNode('ColdToHotRainbow')
        displayNode.SetAndObserveColorNodeID(colorNode.GetID())

    for sliceViewName in ['Red', 'Yellow', 'Green']:
      sliceWidget = layoutManager.sliceWidget(sliceViewName)
      if sliceWidget:
        compositeNode = sliceWidget.mrmlSliceCompositeNode()
        compositeNode.SetBackgroundVolumeID(fixedVolume.GetID())
        compositeNode.SetForegroundVolumeID(registeredVolume.GetID())
        compositeNode.SetForegroundOpacity(0.5)
        sliceWidget.sliceLogic().FitSliceToAll()

  #------------------------------------------------------------------------------
  def onManualTransformChanged(self):
      # Show and enable resample button
      self.step1_2_1_1_resampleButton.visible = True
      self.step1_2_1_1_resampleButton.enabled = True

  #------------------------------------------------------------------------------
  def onResampleMeasured(self):
      if not hasattr(self, 'transformNode') or not hasattr(self, 'registeredPostNode'):
        slicer.util.errorDisplay('Please run registration first')
        return
      
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      
      resampleParameters = {
        'inputVolume': self.registeredPostNode.GetID(),
        'referenceVolume': (self.step1_2_1_1_r1PreSelector.currentNode()
                            if self.step1_2_1_1_useGRECheckBox.isChecked()
                            else self.step1_2_1_preScanSelector.currentNode()).GetID(),
        'outputVolume': self.registeredPostNode.GetID(),
        'pixelType': 'float',
        'warpTransform': self.manualTransformNode.GetID(),
        'interpolationMode': 'Linear'
      }

      slicer.cli.run(slicer.modules.brainsresample, None, resampleParameters, wait_for_completion=True)
      self.registeredPostNode.HardenTransform()
      
      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      selectionNode.SetActiveVolumeID(self.registeredPostNode.GetID())
      selectionNode.SetSecondaryVolumeID((self.step1_2_1_1_r1PreSelector.currentNode()
                                          if self.step1_2_1_1_useGRECheckBox.isChecked()
                                          else self.step1_2_1_preScanSelector.currentNode()).GetID())
      appLogic.PropagateVolumeSelection()
      
      qt.QApplication.restoreOverrideCursor()
      self.step1_2_1_1_resampleButton.enabled = False

  #------------------------------------------------------------------------------
  def onUseGREToggled(self, checked):
    self.step1_2_1_1_applyToR1Button.visible = checked
    self.step1_2_1_1_applyToR1Button.collapsed = not checked

  #------------------------------------------------------------------------------
  def onApplyTransformToR1(self):
    r1PreNode = self.step1_2_1_1_r1PreSelector.currentNode()
    r1PostNode = self.step1_2_1_1_r1PostSelector.currentNode()

    if not r1PreNode or not r1PostNode:
      qt.QMessageBox.warning(None, 'Warning', 'Please select both pre- and post-irradiation R1 maps.')
      return

    if not hasattr(self, 'transformNode') or self.transformNode is None:
      qt.QMessageBox.warning(None, 'Warning', 'No registration transform found. Please run registration first.')
      return

    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
    progressDialog = qt.QProgressDialog("Applying transform to R1 maps...", "OK", 0, 0)
    progressDialog.setModal(True)
    progressDialog.setMinimumDuration(0)
    progressDialog.show()
    slicer.app.processEvents()

    try:
      # Create output node for registered R1 post volume
      outputName = r1PostNode.GetName() + "_registered"
      outputNode = slicer.mrmlScene.GetFirstNodeByName(outputName)
      if outputNode is None:
        outputNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", outputName)

      resampleParameters = {
        'inputVolume': r1PostNode.GetID(),
        'referenceVolume': r1PreNode.GetID(),
        'outputVolume': outputNode.GetID(),
        'pixelType': 'float',
        'warpTransform': self.transformNode.GetID(),
        'interpolationMode': 'Linear',
      }

      cliNode = slicer.cli.run(slicer.modules.brainsresample, None, resampleParameters, wait_for_completion=True)
      progressDialog.close()
      qt.QApplication.restoreOverrideCursor()

      if cliNode.GetStatus() & cliNode.Completed:
        self.registeredPostNode = outputNode
        self.manualTransformNode = slicer.mrmlScene.GetFirstNodeByName("PreToPostManualAdjust")
        if self.manualTransformNode is None:
            self.manualTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "PreToPostManualAdjust")
        else:
          matrix = vtk.vtkMatrix4x4()
          self.manualTransformNode.GetMatrixTransformToParent(matrix)
          matrix.Identity()
          self.manualTransformNode.SetMatrixTransformToParent(matrix)
        outputNode.SetAndObserveTransformNodeID(self.manualTransformNode.GetID())
        self.step1_2_1_1_translationSliders.setMRMLTransformNode(self.manualTransformNode)
        self.step1_2_1_1_rotationSliders.setMRMLTransformNode(self.manualTransformNode)
        self.step1_2_1_1_resampleButton.visible = False
        self.showRegistrationResult(r1PreNode, outputNode)
        self.step1_2_1_1_denoisingInputSelector.setCurrentNode(r1PreNode)
      else:
        qt.QMessageBox.critical(None, 'Error', 'Failed to apply transform to R1 maps')
    except Exception as e:
      progressDialog.close()
      qt.QApplication.restoreOverrideCursor()
      qt.QMessageBox.critical(None, 'Error', f'Failed to apply transform: {str(e)}')
  
  #------------------------------------------------------------------------------
  def onFilterTypeChanged(self, index):
      filterType = self.step1_2_1_1_filterTypeComboBox.currentText
      self.step1_2_1_1_gradientParamsWidget.setVisible(filterType == "Gradient Anisotropic Diffusion")
      self.step1_2_1_1_curvatureParamsWidget.setVisible(filterType == "Curvature Anisotropic Diffusion")
      self.step1_2_1_1_gaussianParamsWidget.setVisible(filterType == "Gaussian Blur Image Filter")
      self.step1_2_1_1_medianParamsWidget.setVisible(filterType == "Median Image Filter")
    
  #------------------------------------------------------------------------------
  def onApplyDenoising(self):
      inputVolume = self.step1_2_1_1_denoisingInputSelector.currentNode()
      
      if not inputVolume:
        qt.QMessageBox.warning(None, 'Warning', 'Please select an input volume.')
        return
      
      filterType = self.step1_2_1_1_filterTypeComboBox.currentText
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      progressDialog = qt.QProgressDialog("Denoising. This may take several seconds.", "OK", 0, 0)
      progressDialog.setWindowModality(qt.Qt.WindowModal)
      progressDialog.show()
      slicer.app.processEvents()
      
      try:
        if filterType == "Gradient Anisotropic Diffusion":
          params = {
            'inputVolume': inputVolume.GetID(),
            'outputVolume': inputVolume.GetID(),
            'numberOfIterations': self.step1_2_1_1_gradientIterationsSpinBox.value,
            'timeStep': self.step1_2_1_1_gradientTimeStepSpinBox.value,
            'conductance': self.step1_2_1_1_gradientConductanceSpinBox.value
          }
          slicer.cli.run(slicer.modules.gradientanisotropicdiffusion, None, params, wait_for_completion=True)
        
        elif filterType == "Curvature Anisotropic Diffusion":
          params = {
            'inputVolume': inputVolume.GetID(),
            'outputVolume': inputVolume.GetID(),
            'numberOfIterations': self.step1_2_1_1_curvatureIterationsSpinBox.value,
            'timeStep': self.step1_2_1_1_curvatureTimeStepSpinBox.value,
            'conductance': self.step1_2_1_1_curvatureConductanceSpinBox.value
          }
          slicer.cli.run(slicer.modules.curvatureanisotropicdiffusion, None, params, wait_for_completion=True)
        
        elif filterType == "Gaussian Blur Image Filter":
          params = {
            'inputVolume': inputVolume.GetID(),
            'outputVolume': inputVolume.GetID(),
            'sigma': self.step1_2_1_1_gaussianSigmaSpinBox.value
          }
          slicer.cli.run(slicer.modules.gaussianblurimagefilter, None, params, wait_for_completion=True)
        
        elif filterType == "Median Image Filter":
          kernelSize = self.step1_2_1_1_medianNeighborhoodSpinBox.value
          params = {
            'inputVolume': inputVolume.GetID(),
            'outputVolume': inputVolume.GetID(),
            'neighborhood': [kernelSize, kernelSize, kernelSize]
          }
          slicer.cli.run(slicer.modules.medianimagefilter, None, params, wait_for_completion=True)
        qt.QApplication.restoreOverrideCursor()
        progressDialog.close()
        qt.QMessageBox.information(None, 'Success', 'Denoising complete.')
        self.showDenoisedResult(inputVolume)
      
      except Exception as e:
        qt.QApplication.restoreOverrideCursor()
        progressDialog.close()
        qt.QMessageBox.critical(None, 'Error', f'Denoising failed: {str(e)}')
  
  #------------------------------------------------------------------------------
  def showDenoisedResult(self, denoisedVolume):
    # Set denoised volume as background in all views
    layoutManager = slicer.app.layoutManager()
    layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(denoisedVolume.GetID())
    selectionNode.SetSecondaryVolumeID(None)
    appLogic.PropagateVolumeSelection()
    
    # Reset field of view in all slice views
    layoutManager = self.layoutWidget.layoutManager()
    threeDWidget = layoutManager.threeDWidget(0)
    if threeDWidget is not None and threeDWidget.threeDView() is not None:
      threeDWidget.threeDView().resetFocalPoint()

  #------------------------------------------------------------------------------
  def onComputeDeltaR(self):
    # Compute Delta R by subtracting pre from registered post
    if self.step1_2_1_1_useGRECheckBox.isChecked():
      preScanNode = self.step1_2_1_1_r1PreSelector.currentNode()
    else:
      preScanNode = self.step1_2_1_preScanSelector.currentNode()
    postScanNode = self.step1_2_1_postScanSelector.currentNode()

    if preScanNode is None:
      qt.QMessageBox.warning(None, 'Warning', 'No pre-irradiation R1 map selected. Please select one in the R1 map section.')
      return
    
    if not preScanNode or not self.registeredPostNode:
      qt.QMessageBox.warning(None, 'Warning', 'Please select both pre- and post-irradiation volumes')
      return
    
    try:
      # Harden any pending transform on the registered post node before subtraction,
      # otherwise the CLI operates on raw untransformed voxel data
      if self.registeredPostNode.GetTransformNodeID():
        self.registeredPostNode.HardenTransform()

      # Create output volume for Delta R
      deltaRNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "DeltaR_Map")
      
      # Subtract pre from post
      parameters = {
        "inputVolume1": self.registeredPostNode.GetID(),
        "inputVolume2": preScanNode.GetID(),
        "outputVolume": deltaRNode.GetID(),
        "order": 1  # Linear interpolation
      }
      
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      
      # Show progress dialog
      progressDialog = qt.QProgressDialog("Computing ΔR1 or ΔR2.", "OK", 0, 0)
      progressDialog.setModal(True)
      progressDialog.setMinimumDuration(0)
      progressDialog.show()
      slicer.app.processEvents()
      
      cliNode = slicer.cli.run(slicer.modules.subtractscalarvolumes, None, parameters, wait_for_completion=True)
      
      progressDialog.close()
      qt.QApplication.restoreOverrideCursor()
      
      if cliNode.GetStatus() & cliNode.Completed:
        self.deltaRNode = deltaRNode
        
        # Set as the measured volume for calibration workflow
        self.measuredVolumeNode = deltaRNode
        
        # Display the Delta R map in 4-up view
        self.showDeltaRResult(deltaRNode)
        
        qt.QMessageBox.information(None, 'Success', 'ΔR1 or ΔR2 map calculated successfully.')
      else:
        qt.QMessageBox.critical(None, 'Error', 'Delta R computation failed')
        slicer.mrmlScene.RemoveNode(deltaRNode)
        
    except Exception as e:
      qt.QApplication.restoreOverrideCursor()
      import traceback
      traceback.print_exc()
      qt.QMessageBox.critical(None, 'Error', f'Delta R computation failed: {str(e)}')
  
  #------------------------------------------------------------------------------
  def showDeltaRResult(self, deltaRVolume):
    # Display Delta R map in 4-up view
    layoutManager = slicer.app.layoutManager()
    layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    
    appLogic = slicer.app.applicationLogic()
    selectionNode = appLogic.GetSelectionNode()
    selectionNode.SetActiveVolumeID(deltaRVolume.GetID())
    selectionNode.SetSecondaryVolumeID(None)
    appLogic.PropagateVolumeSelection()

    displayNode = deltaRVolume.GetDisplayNode()
    if displayNode:
        colorNode = slicer.util.getNode('ColdToHotRainbow')
        displayNode.SetAndObserveColorNodeID(colorNode.GetID())
        displayNode.AutoWindowLevelOn()
    
    layoutManager = self.layoutWidget.layoutManager()
    threeDWidget = layoutManager.threeDWidget(0)
    if threeDWidget is not None and threeDWidget.threeDView() is not None:
      threeDWidget.threeDView().resetFocalPoint()

  #------------------------------------------------------------------------------
  # STEP 1.2.2
  #------------------------------------------------------------------------------
  def onCalibrationPreScanSelected(self, node):
    # Enable Delta R workflow when pre-irradiation calibration volume is selected
    if node:
      self.step1_2_2_1_step2_registrationButton.visible = True
      self.step1_2_2_1_step2_registrationButton.enabled = True
      self.step1_2_2_1_step2_registrationButton.collapsed = False
      self.step1_2_2_1_step3_denoisingButton.visible = True
      self.step1_2_2_1_step4_computeButton.visible = True
    else:
      for btn in [self.step1_2_2_1_step2_registrationButton,
                  self.step1_2_2_1_step3_denoisingButton,
                  self.step1_2_2_1_step4_computeButton]:
        btn.enabled = True
        btn.collapsed = True
        btn.visible = False

  #------------------------------------------------------------------------------
  def onCalibrationPostScanSelected(self, node):
    # Auto-populate calibration volume when post-irradiation volume is selected
    if node:
      # Set post-irradiation volume as the default calibration volume
      self.calibrationVolumeNode = node

  #------------------------------------------------------------------------------
  def onCalibrationRegisterPrePost(self):
    # Register calibration post to pre-irradiation volume using BRAINS
    preScanNode = self.step1_2_2_preScanSelector.currentNode()
    postScanNode = self.step1_2_2_postScanSelector.currentNode()
    
    if not preScanNode or not postScanNode:
      qt.QMessageBox.warning(None, 'Warning', 'Please select both pre and post-irradiation volumes')
      return
    
    try:
      # Create transform node
      transformNode = slicer.mrmlScene.GetFirstNodeByName("CalibrationPreToPostTransform")
      # Reuse existing transform node if present, otherwise create one
      if transformNode is None:
          transformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "CalibrationPreToPostTransform")
      
      # Set up BRAINS registration parameters
      parameters = {
        "fixedVolume": preScanNode.GetID(),
        "movingVolume": postScanNode.GetID(),
        "linearTransform": transformNode.GetID(),
        "samplingPercentage": 0.02,
        "initializeTransformMode": "useMomentsAlign",
        "useRigid": True
      }
      
      # Run BRAINS registration
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      progressDialog = qt.QProgressDialog("Performing registration. This may take several seconds.", "OK", 0, 0)
      progressDialog.setModal(True)
      progressDialog.setMinimumDuration(0)
      progressDialog.show()
      slicer.app.processEvents()
      
      cliNode = slicer.cli.run(slicer.modules.brainsfit, None, parameters, wait_for_completion=True)
      
      if cliNode.GetStatus() & cliNode.Completed:
        # Create output node for registered calibration post volume
        outputName = postScanNode.GetName() + "_registered"
        outputNode = slicer.mrmlScene.GetFirstNodeByName(outputName)
        if outputNode is None:
          outputNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", outputName)

        resampleParameters = {
          "inputVolume": postScanNode.GetID(),
          "referenceVolume": preScanNode.GetID(),
          "outputVolume": outputNode.GetID(),
          "pixelType": "float",
          "warpTransform": transformNode.GetID(),
          "interpolationMode": "Linear"
        }
        
        cliNode2 = slicer.cli.run(slicer.modules.brainsresample, None, resampleParameters, wait_for_completion=True)
        
        progressDialog.close()
        qt.QApplication.restoreOverrideCursor()
        
        if cliNode2.GetStatus() & cliNode2.Completed:
          self.calibrationRegisteredPostNode = outputNode
          self.calibrationTransformNode = transformNode
          
          # Enable Steps 3 and 4
          self.step1_2_2_1_step3_denoisingButton.enabled = True
          self.step1_2_2_1_step4_computeButton.enabled = True
          self.step1_2_2_1_computeDeltaRButton.enabled = True
          self.step1_2_2_1_useGRECheckBox.enabled = True
          
          # Set default noising input to pre-irradiation volume
          self.step1_2_2_1_denoisingInputSelector.setCurrentNode(preScanNode)

          # Show registere result
          self.showRegistrationResult(preScanNode, outputNode)

          # Create separate manual adjustment rasnform
          self.calibrationManualTransformNode = slicer.mrmlScene.GetFirstNodeByName("CalibrationPreToPostManualAdjust")
          if self.calibrationManualTransformNode is None:
              self.calibrationManualTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "CalibrationPreToPostManualAdjust")
          else:
              matrix = vtk.vtkMatrix4x4()
              self.calibrationManualTransformNode.GetMatrixTransformToParent(matrix)
              matrix.Identity()
              self.calibrationManualTransformNode.SetMatrixTransformToParent(matrix)
          outputNode.SetAndObserveTransformNodeID(self.calibrationManualTransformNode.GetID())
          self.step1_2_2_1_translationSliders.setMRMLTransformNode(self.calibrationManualTransformNode)
          self.step1_2_2_1_rotationSliders.setMRMLTransformNode(self.calibrationManualTransformNode)
          self.step1_2_2_1_resampleButton.visible = False
        else:
          qt.QMessageBox.critical(None, 'Error', 'Resampling failed')
      else:
        progressDialog.close()
        qt.QApplication.restoreOverrideCursor()
        qt.QMessageBox.critical(None, 'Error', 'Registration failed')
        slicer.mrmlScene.RemoveNode(transformNode)
        
    except Exception as e:
      qt.QApplication.restoreOverrideCursor()
      import traceback
      traceback.print_exc()
      qt.QMessageBox.critical(None, 'Error', f'Registration failed: {str(e)}')
  
  #------------------------------------------------------------------------------
  def onCalibrationManualTransformChanged(self):
    # Show and enable resample button
    self.step1_2_2_1_resampleButton.visible = True
    self.step1_2_2_1_resampleButton.enabled = True

  #------------------------------------------------------------------------------
  def onResampleCalibration(self):
      if not hasattr(self, 'calibrationTransformNode') or not hasattr(self, 'calibrationRegisteredPostNode'):
          slicer.util.errorDisplay('Please run calibration registration first')
          return

      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

      resampleParameters = {
          'inputVolume': self.calibrationRegisteredPostNode.GetID(),
          'referenceVolume': (self.step1_2_2_1_r1PreSelector.currentNode()
                              if self.step1_2_2_1_useGRECheckBox.isChecked()
                              else self.step1_2_2_preScanSelector.currentNode()).GetID(),
          'outputVolume': self.calibrationRegisteredPostNode.GetID(),
          'pixelType': 'float',
          'warpTransform': self.calibrationManualTransformNode.GetID(),
          'interpolationMode': 'Linear',
      }

      slicer.cli.run(slicer.modules.brainsresample, None, resampleParameters, wait_for_completion=True)
      self.calibrationRegisteredPostNode.HardenTransform()

      appLogic = slicer.app.applicationLogic()
      selectionNode = appLogic.GetSelectionNode()
      selectionNode.SetActiveVolumeID(self.calibrationRegisteredPostNode.GetID())
      selectionNode.SetSecondaryVolumeID((self.step1_2_2_1_r1PreSelector.currentNode()
                                          if self.step1_2_2_1_useGRECheckBox.isChecked()
                                          else self.step1_2_2_preScanSelector.currentNode()).GetID())
      appLogic.PropagateVolumeSelection()

      qt.QApplication.restoreOverrideCursor()
      self.step1_2_2_1_resampleButton.enabled = False

  #------------------------------------------------------------------------------
  def onCalibrationUseGREToggled(self, checked):
    self.step1_2_2_1_applyToR1Button.visible = checked
    self.step1_2_2_1_applyToR1Button.collapsed = not checked

  #------------------------------------------------------------------------------
  def onCalibrationApplyTransformToR1(self):
    r1PreNode = self.step1_2_2_1_r1PreSelector.currentNode()
    r1PostNode = self.step1_2_2_1_r1PostSelector.currentNode()

    if not r1PreNode or not r1PostNode:
      qt.QMessageBox.warning(None, 'Warning', 'Please select both R1 pre- and post-irradiation maps')
      return

    if not hasattr(self, 'calibrationTransformNode') or self.calibrationTransformNode is None:
      qt.QMessageBox.warning(None, 'Warning', 'No registration transform found. Please run calibration registration first.')
      return

    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
    progressDialog = qt.QProgressDialog("Applying transform to R1 maps...", "OK", 0, 0)
    progressDialog.setModal(True)
    progressDialog.setMinimumDuration(0)
    progressDialog.show()
    slicer.app.processEvents()

    try:
      # Create output node for registered calibration R1 post volume
      outputName = r1PostNode.GetName() + "_registered"
      outputNode = slicer.mrmlScene.GetFirstNodeByName(outputName)
      if outputNode is None:
        outputNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", outputName)

      resampleParameters = {
        'inputVolume': r1PostNode.GetID(),
        'referenceVolume': r1PreNode.GetID(),
        'outputVolume': outputNode.GetID(),
        'pixelType': 'float',
        'warpTransform': self.calibrationTransformNode.GetID(),
        'interpolationMode': 'Linear'
      }

      cliNode = slicer.cli.run(slicer.modules.brainsresample, None, resampleParameters, wait_for_completion=True)
      progressDialog.close()
      qt.QApplication.restoreOverrideCursor()

      if cliNode.GetStatus() & cliNode.Completed:
        self.calibrationRegisteredPostNode = outputNode
        self.calibrationManualTransformNode = slicer.mrmlScene.GetFirstNodeByName("CalibrationPreToPostManualAdjust")
        if self.calibrationManualTransformNode is None:
            self.calibrationManualTransformNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLinearTransformNode", "CalibrationPreToPostManualAdjust")
        else:
            matrix = vtk.vtkMatrix4x4()
            self.calibrationManualTransformNode.GetMatrixTransformToParent(matrix)
            matrix.Identity()
            self.calibrationManualTransformNode.SetMatrixTransformToParent(matrix)
        outputNode.SetAndObserveTransformNodeID(self.calibrationManualTransformNode.GetID())
        self.step1_2_2_1_translationSliders.setMRMLTransformNode(self.calibrationManualTransformNode)
        self.step1_2_2_1_rotationSliders.setMRMLTransformNode(self.calibrationManualTransformNode)
        self.step1_2_2_1_resampleButton.visible = False
        self.showRegistrationResult(r1PreNode, outputNode)
        self.step1_2_2_1_denoisingInputSelector.setCurrentNode(r1PreNode)
      else:
        qt.QMessageBox.critical(None, 'Error', 'Failed to apply transform to R1 maps')
    except Exception as e:
      progressDialog.close()
      qt.QApplication.restoreOverrideCursor()
      qt.QMessageBox.critical(None, 'Error', f'Failed to apply transform: {str(e)}')

  #------------------------------------------------------------------------------
  def onCalibrationFilterTypeChanged(self, index):
    filterType = self.step1_2_2_1_filterTypeComboBox.currentText
    self.step1_2_2_1_gradientParamsWidget.setVisible(filterType == "Gradient Anisotropic Diffusion")
    self.step1_2_2_1_curvatureParamsWidget.setVisible(filterType == "Curvature Anisotropic Diffusion")
    self.step1_2_2_1_gaussianParamsWidget.setVisible(filterType == "Gaussian Blur Image Filter")
    self.step1_2_2_1_medianParamsWidget.setVisible(filterType == "Median Image Filter")

  #------------------------------------------------------------------------------
  def onCalibrationApplyDenoising(self):
      inputVolume = self.step1_2_2_1_denoisingInputSelector.currentNode()
      
      if not inputVolume:
        qt.QMessageBox.warning(None, 'Warning', 'Please select an input volume.')
       
        return
      
      filterType = self.step1_2_2_1_filterTypeComboBox.currentText
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      progressDialog = qt.QProgressDialog("Denoising. This may take several seconds.", "OK", 0, 0)
      progressDialog.setWindowModality(qt.Qt.WindowModal)
      progressDialog.show()
      slicer.app.processEvents()
      
      try:
        if filterType == "Gradient Anisotropic Diffusion":
          params = {
            'inputVolume': inputVolume.GetID(),
            'outputVolume': inputVolume.GetID(),
            'numberOfIterations': self.step1_2_2_1_gradientIterationsSpinBox.value,
            'timeStep': self.step1_2_2_1_gradientTimeStepSpinBox.value,
            'conductance': self.step1_2_2_1_gradientConductanceSpinBox.value
          }
          slicer.cli.run(slicer.modules.gradientanisotropicdiffusion, None, params, wait_for_completion=True)
        
        elif filterType == "Curvature Anisotropic Diffusion":
          params = {
            'inputVolume': inputVolume.GetID(),
            'outputVolume': inputVolume.GetID(),
            'numberOfIterations': self.step1_2_2_1_curvatureIterationsSpinBox.value,
            'timeStep': self.step1_2_2_1_curvatureTimeStepSpinBox.value,
            'conductance': self.step1_2_2_1_curvatureConductanceSpinBox.value
          }
          slicer.cli.run(slicer.modules.curvatureanisotropicdiffusion, None, params, wait_for_completion=True)          
        
        elif filterType == "Gaussian Blur Image Filter":
          params = {
            'inputVolume': inputVolume.GetID(),
            'outputVolume': inputVolume.GetID(),
            'sigma': self.step1_2_2_1_gaussianSigmaSpinBox.value
          }
          slicer.cli.run(slicer.modules.gaussianblurimagefilter, None, params, wait_for_completion=True)
        
        elif filterType == "Median Image Filter":
          kernelSize = self.step1_2_2_1_medianNeighborhoodSpinBox.value
          params = {
            'inputVolume': inputVolume.GetID(),
            'outputVolume': inputVolume.GetID(),
            'neighborhood': [kernelSize, kernelSize, kernelSize]
          }
          slicer.cli.run(slicer.modules.medianimagefilter, None, params, wait_for_completion=True)
        qt.QApplication.restoreOverrideCursor()
        progressDialog.close()
        qt.QMessageBox.information(None, 'Success', 'Denoising complete.')
        self.showDenoisedResult(inputVolume)
  
      except Exception as e:
        qt.QApplication.restoreOverrideCursor()
        progressDialog.close()
        qt.QMessageBox.critical(None, 'Error', f'Denoising failed: {str(e)}')

  #------------------------------------------------------------------------------
  def onCalibrationComputeDeltaR(self):
    # Compute Delta R for calibration gel by subtracting pre from registered post
    if self.step1_2_2_1_useGRECheckBox.isChecked():
      preScanNode = self.step1_2_2_1_r1PreSelector.currentNode()
    else:
      preScanNode = self.step1_2_2_preScanSelector.currentNode()
    postScanNode = self.step1_2_2_postScanSelector.currentNode()

    if preScanNode is None:
      qt.QMessageBox.warning(None, 'Warning', 'No pre-irradiation R1 map selected. Please select one in the R1 map section.')
      return
    
    if not preScanNode or not self.calibrationRegisteredPostNode:
      qt.QMessageBox.warning(None, 'Warning', 'Please select both pre and post-irradiation volumes')
      return
    
    try:
      # Harden any pending transform on the registered post node before subtraction,
      # otherwise the CLI operates on raw untransformed voxel data
      if self.calibrationRegisteredPostNode.GetTransformNodeID():
        self.calibrationRegisteredPostNode.HardenTransform()

      # Create output volume for Delta R
      deltaRNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "CalibrationDeltaR_Map")
      
      # Subtract pre from post
      parameters = {
        "inputVolume1": self.calibrationRegisteredPostNode.GetID(),
        "inputVolume2": preScanNode.GetID(),
        "outputVolume": deltaRNode.GetID(),
        "order": 1
      }
      
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      
      # Show progress dialog
      progressDialog = qt.QProgressDialog("Computing ΔR1 or ΔR2.", "OK", 0, 0)
      progressDialog.setModal(True)
      progressDialog.setMinimumDuration(0)
      progressDialog.show()
      slicer.app.processEvents()
      
      cliNode = slicer.cli.run(slicer.modules.subtractscalarvolumes, None, parameters, wait_for_completion=True)
      
      progressDialog.close()
      qt.QApplication.restoreOverrideCursor()
      
      if cliNode.GetStatus() & cliNode.Completed:
        self.calibrationDeltaRNode = deltaRNode
        
        # Set as the calibration volume for the workflow
        self.calibrationVolumeNode = deltaRNode
        
        # Display the Delta R map in 4-up view
        self.showDeltaRResult(deltaRNode)
        
        qt.QMessageBox.information(None, 'Success', 'ΔR1 or ΔR2 map calculated successfully.')
      else:
        qt.QMessageBox.critical(None, 'Error', 'Delta R computation failed')
        slicer.mrmlScene.RemoveNode(deltaRNode)
        
    except Exception as e:
      qt.QApplication.restoreOverrideCursor()
      import traceback
      traceback.print_exc()
      qt.QMessageBox.critical(None, 'Error', f'Delta R computation failed: {str(e)}')

#
# GelDosimetryAnalysis
#
class GelDosimetryAnalysis(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    parent.title = "Gel Dosimetry Analysis"
    parent.categories = ["Slicelets"]
    parent.dependencies = ["GelDosimetryAnalysisAlgo", "DicomRtImportExport", "VffFileReader", "DoseComparison", "BRAINSFit", "BRAINSResample", "Markups", "DataProbe"]
    parent.contributors = ["Csaba Pinter (Queen's University), Mattea Welch (Queen's University), Jennifer Andrea (Queen's University), Kevin Alexander (Kingston General Hospital)"] # replace with "Firstname Lastname (Org)"
    parent.helpText = "Slicelet for gel dosimetry analysis"
    parent.acknowledgementText = """
    This file was originally developed by Mattea Welch, Jennifer Andrea, and Csaba Pinter (Queen's University). Funding was provided by NSERC-USRA, OCAIRO, Cancer Care Ontario and Queen's University
    """
    iconPath = os.path.join(os.path.dirname(self.parent.path), 'Resources/Icons', self.moduleName+'.png')
    parent.icon = qt.QIcon(iconPath)

#
# GelDosimetryAnalysisWidget
#
class GelDosimetryAnalysisWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Show slicelet button
    showSliceletButton = qt.QPushButton("Show slicelet")
    showSliceletButton.toolTip = "Launch the slicelet"
    self.layout.addWidget(qt.QLabel(' '))
    self.layout.addWidget(showSliceletButton)
    showSliceletButton.connect('clicked()', self.launchSlicelet)

    # Add vertical spacer
    self.layout.addStretch(1)

  def launchSlicelet(self):
    mainFrame = SliceletMainFrame()
    mainFrame.minimumWidth = 1200
    mainFrame.minimumHeight = 720
    mainFrame.windowTitle = "Gel dosimetry analysis"
    mainFrame.setWindowFlags(qt.Qt.WindowCloseButtonHint | qt.Qt.WindowMaximizeButtonHint | qt.Qt.WindowTitleHint)
    iconPath = os.path.join(os.path.dirname(slicer.modules.geldosimetryanalysis.path), 'Resources/Icons', self.moduleName+'.png')
    mainFrame.windowIcon = qt.QIcon(iconPath)
    mainFrame.connect('destroyed()', self.onSliceletClosed)

    slicelet = GelDosimetryAnalysisSlicelet(mainFrame, self.developerMode)
    mainFrame.setSlicelet(slicelet)

    # Make the slicelet reachable from the Slicer python interactor for testing
    slicer.gelDosimetrySliceletInstance = slicelet

    return slicelet

  def onSliceletClosed(self):
    logging.debug('Slicelet closed')

# ---------------------------------------------------------------------------
class GelDosimetryAnalysisTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  #------------------------------------------------------------------------------
  def test_GelDosimetryAnalysis_FullTest(self):
    try:
      # Check for modules
      self.assertIsNotNone( slicer.modules.geldosimetryanalysisalgo )
      self.assertIsNotNone( slicer.modules.dicomrtimportexport )
      self.assertIsNotNone( slicer.modules.vfffilereader )
      self.assertIsNotNone( slicer.modules.dosecomparison )
      self.assertIsNotNone( slicer.modules.subjecthierarchy )
      self.assertIsNotNone( slicer.modules.segmentations )
      self.assertIsNotNone( slicer.modules.brainsfit )
      self.assertIsNotNone( slicer.modules.brainsresample )
      self.assertIsNotNone( slicer.modules.markups )
      self.assertIsNotNone( slicer.modules.dataprobe )

      self.TestSection_00_SetupPathsAndNames()
      self.TestSection_01_LoadDicomData()
      self.TestSection_02_FinalizeDataLoading()
      self.TestSection_03_Register()
      self.TestSection_04_Calibrate()
      self.TestSection_05_CompareDoses()

    except Exception as e:
      logging.error('Exception happened! Details:')
      import traceback
      traceback.print_exc()

  #------------------------------------------------------------------------------
  def TestSection_00_SetupPathsAndNames(self):
    gelDosimetryAnalysisDir = slicer.app.temporaryPath + '/GelDosimetryAnalysis'
    if not os.access(gelDosimetryAnalysisDir, os.F_OK):
      os.mkdir(gelDosimetryAnalysisDir)

    self.dicomDataDir = gelDosimetryAnalysisDir + '/GelDosimetryAnalysisDicom'
    if not os.access(self.dicomDataDir, os.F_OK):
      os.mkdir(self.dicomDataDir)

    self.dicomDatabaseDir = gelDosimetryAnalysisDir + '/CtkDicomDatabase'
    self.dicomZipFileUrl = 'http://slicer.kitware.com/midas3/download/item/300651/GelDosimetryTestData.zip'
    self.dicomZipFilePath = gelDosimetryAnalysisDir + '/GelDosimetryTestData.zip'
    self.expectedNumOfFilesInDicomDataDir = 328
    self.tempDir = gelDosimetryAnalysisDir + '/Temp'

    self.planningVolumeName = '47: ARIA RadOnc Images - Verification Plan Phantom'
    self.planDoseVolumeName = '53: RTDOSE: Eclipse Doses: VMAT XM1 LCV'
    self.igrtVolumeName = '0: Unnamed Series'
    self.structureSetNodeName = '52: RTSTRUCT: CT_1'
    self.measuredVolumeName = 'LCV01_HR_plan (lcv01_hr)'
    self.calibrationVolumeName = 'LCV02_HR_calib (lcv02_hr)'
    self.maskSegmentID = 'Jar_crop'

    self.slicelet = None

    self.setupPathsAndNamesDone = True

  #------------------------------------------------------------------------------
  def TestSection_01_LoadDicomData(self):
    try:
      # Open test database and empty it
      with DICOMUtils.TemporaryDICOMDatabase(self.dicomDatabaseDir) as db:
        self.assertTrue( db.isOpen )
        self.assertEqual( slicer.dicomDatabase, db)

        # Download, unzip, import, and load data. Verify selected plugins and loaded nodes.
        selectedPlugins = { 'Scalar Volume':2, 'RT':3 }
        loadedNodes = { 'vtkMRMLScalarVolumeNode':3, \
                        'vtkMRMLSegmentationNode':1, \
                        'vtkMRMLRTPlanNode':1, \
                        'vtkMRMLRTBeamNode':1, \
                        'vtkMRMLMarkupsFiducialNode':1 }
        with DICOMUtils.LoadDICOMFilesToDatabase( \
            self.dicomZipFileUrl, self.dicomZipFilePath, \
            self.dicomDataDir, self.expectedNumOfFilesInDicomDataDir, \
            {}, loadedNodes) as success:
          self.assertTrue(success)

          # slicer.app.processEvents()
          # qt.QMessageBox.information(None,"Done","DICOM files loaded successfully.")
          self.delayDisplay("DICOM files loaded successfully.")

    except Exception as e:
      import traceback
      traceback.print_exc()
      self.delayDisplay('Test caused exception!\n' + str(e),self.delayMs*2)

  #------------------------------------------------------------------------------
  def TestSection_02_FinalizeDataLoading(self):
    self.delayDisplay("Perform registration",self.delayMs)

    try:
      slicer.util.selectModule('GelDosimetryAnalysis')
      moduleWidget = slicer.modules.geldosimetryanalysis.widgetRepresentation().self()

      # Show slicelet
      self.slicelet = moduleWidget.launchSlicelet()
      self.assertIsNotNone(self.slicelet)

      self.slicelet.mode = 'Clinical'
      self.slicelet.step1_loadDataCollapsibleButton.setChecked(True)

      # Load non-DICOM data
      vffFilesDir = self.dicomDataDir + '/VFFs'
      numOfScalarVolumeNodesBeforeLoad = len( slicer.util.getNodes('vtkMRMLScalarVolumeNode*') )
      slicer.util.loadNodeFromFile(vffFilesDir + '/LCV01_HR_plan.vff', 'VffFile', {})
      slicer.util.loadNodeFromFile(vffFilesDir + '/LCV02_HR_calib.vff', 'VffFile', {})
      # Verify that the VFF files were loaded
      self.assertEqual( len( slicer.util.getNodes('vtkMRMLScalarVolumeNode*') ), numOfScalarVolumeNodesBeforeLoad + 2 )

      self.delayDisplay("VFF files loaded successfully.")
      # slicer.app.processEvents()
      # qt.QMessageBox.information(None,"Done","VFF files loaded successfully.")

      # Assign roles
      planningVolume = slicer.util.getNode(self.planningVolumeName)
      self.assertIsNotNone(planningVolume)
      self.slicelet.planningSelector.setCurrentNode(planningVolume)

      planDoseVolume = slicer.util.getNode(self.planDoseVolumeName)
      self.assertIsNotNone(planDoseVolume)
      self.slicelet.planDoseSelector.setCurrentNode(planDoseVolume)

      igrtVolume = slicer.util.getNode(self.igrtVolumeName)
      self.assertIsNotNone(igrtVolume)
      self.slicelet.igrtSelector.setCurrentNode(igrtVolume)

      structureSetNode = slicer.util.getNode(self.structureSetNodeName)
      self.assertIsNotNone(structureSetNode)
      self.slicelet.planStructuresSelector.setCurrentNode(structureSetNode)

      measuredVolume = slicer.util.getNode(self.measuredVolumeName)
      self.assertIsNotNone(measuredVolume)
      self.slicelet.measuredVolumeSelector.setCurrentNode(measuredVolume)

      calibrationVolume = slicer.util.getNode(self.calibrationVolumeName)
      self.assertIsNotNone(calibrationVolume)
      self.slicelet.calibrationVolumeSelector.setCurrentNode(calibrationVolume)

      slicer.app.processEvents()

    except Exception as e:
      import traceback
      traceback.print_exc()
      self.delayDisplay('Test caused exception!\n' + str(e),self.delayMs*2)
      raise Exception("Exception occurred, handled, thrown further to workflow level")

  #------------------------------------------------------------------------------
  def TestSection_03_Register(self):
    self.delayDisplay("Register planning volume to IGRT volume automatically and Measured dose to IGRT volume using fiducials",self.delayMs)

    try:
      self.assertIsNotNone(self.slicelet)

      self.slicelet.step2_registrationCollapsibleButton.setChecked(True)
      igrtToPlanningTransformNode = self.slicelet.onPlanningToIGRTAutomaticRegistration()
      slicer.app.processEvents()

      self.assertIsNotNone(igrtToPlanningTransformNode)
      igrtToPlanningTransformMatrix = igrtToPlanningTransformNode.GetTransformToParent().GetMatrix()
      self.assertAlmostEqual(igrtToPlanningTransformMatrix.GetElement(0,3), 124.44, 0)
      self.assertAlmostEqual(igrtToPlanningTransformMatrix.GetElement(1,3), 182.36, 0)
      self.assertAlmostEqual(igrtToPlanningTransformMatrix.GetElement(2,3) / 2.4,  0, -1) # +/- 12 in Z direction
      self.assertAlmostEqual(igrtToPlanningTransformMatrix.GetElement(0,0), 1.0, 1)
      self.assertAlmostEqual(igrtToPlanningTransformMatrix.GetElement(1,1), 1.0, 1)
      self.assertAlmostEqual(igrtToPlanningTransformMatrix.GetElement(2,2), 1.0, 1)

      # Select fiducials
      self.slicelet.step2_2_measuredDoseToIgrtRegistrationCollapsibleButton.setChecked(True)
      igrtFiducialsNode = slicer.util.getNode(self.slicelet.igrtMarkupsFiducialNode_WithMeasuredName)
      igrtFiducialsNode.AddFiducial(76.4, 132.1, -44.8)
      igrtFiducialsNode.AddFiducial(173, 118.4, -44.8)
      igrtFiducialsNode.AddFiducial(154.9, 163.5, -44.8)
      igrtFiducialsNode.AddFiducial(77.4, 133.6, 23.9)
      igrtFiducialsNode.AddFiducial(172.6, 118.9, 23.9)
      igrtFiducialsNode.AddFiducial(166.5, 151.3, 23.9)

      self.slicelet.step2_2_2_measuredFiducialSelectionCollapsibleButton.setChecked(True)
      measuredFiducialsNode = slicer.util.getNode(self.slicelet.measuredMarkupsFiducialNodeName)
      measuredFiducialsNode.AddFiducial(-92.25, -25.9, 26.2)
      measuredFiducialsNode.AddFiducial(-31.9, -100.8, 26.2)
      measuredFiducialsNode.AddFiducial(-15, -55.2, 26.2)
      measuredFiducialsNode.AddFiducial(-92, -26.7, 94)
      measuredFiducialsNode.AddFiducial(-32.7, -101, 94)
      measuredFiducialsNode.AddFiducial(-15, -73.6, 94)

      # Perform fiducial registration
      self.slicelet.step2_2_3_measuredToIgrtRegistrationCollapsibleButton.setChecked(True)
      igrtToMeasuredTransformNode = self.slicelet.onMeasuredToIgrtRegistration()
      self.assertIsNotNone(igrtToMeasuredTransformNode)
      igrtToMeasuredTransformMatrix = igrtToMeasuredTransformNode.GetTransformToParent().GetMatrix()
      self.assertAlmostEqual(igrtToMeasuredTransformMatrix.GetElement(0,3), 127.70, 0)
      self.assertAlmostEqual(igrtToMeasuredTransformMatrix.GetElement(1,3), 213.64, 0)
      self.assertAlmostEqual(igrtToMeasuredTransformMatrix.GetElement(2,3), -71.98, 0)
      self.assertAlmostEqual(igrtToMeasuredTransformMatrix.GetElement(0,0), 0.73, 1)
      self.assertAlmostEqual(igrtToMeasuredTransformMatrix.GetElement(1,1), 0.73, 1)
      self.assertAlmostEqual(igrtToMeasuredTransformMatrix.GetElement(2,2), 1.00, 1)

    except Exception as e:
      import traceback
      traceback.print_exc()
      self.delayDisplay('Test caused exception!\n' + str(e),self.delayMs*2)
      raise Exception("Exception occurred, handled, thrown further to workflow level")

  #------------------------------------------------------------------------------
  def TestSection_04_Calibrate(self):
    self.delayDisplay("Perform calibration",self.delayMs)

    try:
      self.assertIsNotNone(self.slicelet)

      # Load PDD
      self.slicelet.step3_doseCalibrationCollapsibleButton.setChecked(True)
      pddLoadSuccessful = self.slicelet.logic.loadPdd(self.dicomDataDir + '/12MeV.csv')
      self.assertTrue(pddLoadSuccessful)

      # Parse calibration volume
      self.slicelet.step3_1_radiusMmFromCentrePixelLineEdit.setText('5')

      # Align calibration curves
      alignCalibrationCurvesSuccessful = self.slicelet.onAlignCalibrationCurves()
      self.assertTrue(alignCalibrationCurvesSuccessful)

      self.slicelet.step3_1_xTranslationSpinBox.setValue(1)
      self.slicelet.step3_1_yScaleSpinBox.setValue(1.162)
      self.slicelet.step3_1_yTranslationSpinBox.setValue(1.28)

      # Generate dose information
      self.slicelet.step3_doseCalibrationCollapsibleButton.setChecked(True)
      self.slicelet.step3_1_rdfLineEdit.setText('0.989')
      self.slicelet.step3_1_monitorUnitsLineEdit.setText('1850')
      computeDoseFromPddSuccessful = self.slicelet.onComputeDoseFromPdd()
      self.assertTrue(computeDoseFromPddSuccessful)

      # Show ΔR1 or ΔR2 VS dose curve
      self.slicelet.step3_1_calibrationRoutineCollapsibleButton.setChecked(True)
      self.slicelet.onShowDeltaRVsDoseCurve()

      # Fit polynomial on ΔR1 or ΔR2 VS dose curve
      self.slicelet.onFitPolynomialToDeltaRVsDoseCurve()

      # Calibrate
      applyCalibrationSuccessful = self.slicelet.onApplyCalibration()
      self.assertTrue(applyCalibrationSuccessful)

      # Check calibrated dose volume statistics
      self.assertIsNotNone(self.slicelet.calibratedMeasuredVolumeNode)
      imageAccumulate = vtk.vtkImageAccumulate()
      imageAccumulate.SetInputConnection(self.slicelet.calibratedMeasuredVolumeNode.GetImageDataConnection())
      imageAccumulate.Update()

      doseMax = imageAccumulate.GetMax()[0]
      doseMean = imageAccumulate.GetMean()[0]
      doseStdDev = imageAccumulate.GetStandardDeviation()[0]
      doseVoxelCount = imageAccumulate.GetVoxelCount()
      logging.info("Dose volume properties:\n  Max=" + str(doseMax) + ", Mean=" + str(doseMean) + ", StdDev=" + str(doseStdDev) + ", NumberOfVoxels=" + str(doseVoxelCount))

      self.assertAlmostEqual(doseMax, 836.24, 0)
      self.assertAlmostEqual(doseMean, 3.485419, 2)
      self.assertAlmostEqual(doseStdDev, 5.691135, 2)
      self.assertEqual(doseVoxelCount, 16777216)

      slicer.app.processEvents()
      self.delayDisplay('Wait for the slicelet to catch up', 300)

    except Exception as e:
      import traceback
      traceback.print_exc()
      self.delayDisplay('Test caused exception!\n' + str(e),self.delayMs*2)
      raise Exception("Exception occurred, handled, thrown further to workflow level")

  #------------------------------------------------------------------------------
  def TestSection_05_CompareDoses(self):
    self.delayDisplay("Perform gamma dose comparison",self.delayMs)

    try:
      self.assertIsNotNone(self.slicelet)
      self.slicelet.step4_doseComparisonCollapsibleButton.setChecked(True)

      # Create gamma output node
      numOfScalarVolumeNodesBeforeLoad = len( slicer.util.getNodes('vtkMRMLScalarVolumeNode*') )
      self.slicelet.step4_1_gammaVolumeSelector.addNode()
      gammaVolumeNode = self.slicelet.step4_1_gammaVolumeSelector.currentNode()
      self.assertEqual( len( slicer.util.getNodes('vtkMRMLScalarVolumeNode*') ), numOfScalarVolumeNodesBeforeLoad + 1 )
      self.assertIsNotNone(gammaVolumeNode)

      # Set gamma mask
      structureSetNode = slicer.util.getNode(self.structureSetNodeName)
      self.assertIsNotNone(structureSetNode)
      self.slicelet.step4_maskSegmentationSelector.setCurrentNodeID(structureSetNode.GetID())
      self.slicelet.step4_maskSegmentationSelector.setCurrentSegmentID(self.maskSegmentID)

      # Calculate gamma
      gammaCalculationSuccessful = self.slicelet.onGammaDoseComparison()
      self.assertTrue(gammaCalculationSuccessful)

      # Check gamma volume statistics
      imageAccumulate = vtk.vtkImageAccumulate()
      imageAccumulate.SetInputConnection(gammaVolumeNode.GetImageDataConnection())
      imageAccumulate.Update()

      gammaMax = imageAccumulate.GetMax()[0]
      gammaMean = imageAccumulate.GetMean()[0]
      gammaStdDev = imageAccumulate.GetStandardDeviation()[0]
      gammaVoxelCount = imageAccumulate.GetVoxelCount()
      logging.info("Gamma volume properties:\n  Max=" + str(gammaMax) + ", Mean=" + str(gammaMean) + ", StdDev=" + str(gammaStdDev) + ", NumberOfVoxels=" + str(gammaVoxelCount))

      self.assertAlmostEqual(gammaMax, 2.0, 1)
      self.assertAlmostEqual(gammaMean, 0.025, 1)
      self.assertEqual(gammaVoxelCount, 2076255)
      self.assertIsNotNone(self.slicelet.gammaParameterSetNode)
      self.assertGreater(self.slicelet.gammaParameterSetNode.GetPassFractionPercent(), 0.6)

    except Exception as e:
      import traceback
      traceback.print_exc()
      self.delayDisplay('Test caused exception!\n' + str(e),self.delayMs*2)
      raise Exception("Exception occurred, handled, thrown further to workflow level")

  #------------------------------------------------------------------------------
  # Mandatory functions
  #------------------------------------------------------------------------------
  def setUp(self, clearScene=True):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    if clearScene:
      slicer.mrmlScene.Clear(0)

    self.delayMs = 700

    self.moduleName = "GelDosimetryAnalysis"

  #------------------------------------------------------------------------------
  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()

    self.test_GelDosimetryAnalysis_FullTest()

#
# Main
#
if __name__ == "__main__":
  #TODO: access and parse command line arguments
  #   Example: SlicerRt/src/BatchProcessing
  #   Ideally handle --xml

  import sys
  logging.debug( sys.argv )

  mainFrame = qt.QFrame()
  slicelet = GelDosimetryAnalysisSlicelet(mainFrame)