import os
from __main__ import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
from math import *
import numpy
import time
import slicer.util
from vtk.util import numpy_support

#
# GelDosimetryAnalysisLogic
#
class GelDosimetryAnalysisMRLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self):
    # Define constants
    self.igrtToPlanningTransformName = 'igrtToPlanningTransform'
    self.igrtToMeasuredTransformName = 'igrtToMeasuredTransform'

    # Declare member variables (mainly for documentation)
    self.pddDataArray = None
    self.calculatedDose = None # Computed from Pdd usinh RDF and Electron MUs
    self.calibrationDataArray = None
    self.calibrationDataAlignedArray = None # Calibration array registered (X shift) to the Pdd curve (for computation)
    self.calibrationDataAlignedToDisplayArray = None # Calibration array registered (X shift, Y scale, Y shift) to the Pdd curve (for visual alignment)
    self.deltaRVsDoseFunction = None
    self.calibrationPolynomialCoefficients = None # Calibration polynomial coefficients, highest power first

    # Set logic instance to the global variable that supplies it to the calibration curve alignment minimizer function
    global gelDosimetryLogicInstanceGlobal
    gelDosimetryLogicInstanceGlobal = self

  # ---------------------------------------------------------------------------
  # Show and select DICOM browser
  def onDicomLoad(self):
    slicer.modules.dicom.widgetRepresentation()
    slicer.modules.DICOMWidget.enter()

  # ---------------------------------------------------------------------------
  # Use BRAINS registration to register planning volume to IGRT volume
  # and apply the result to the planning volume and PlanDose
  def registerPlanningToIGRTAutomatic(self, planningVolumeID, igrtVolumeID):
    try:
        qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
        parametersRigid = {}
        parametersRigid["fixedVolume"] = igrtVolumeID
        parametersRigid["movingVolume"] = planningVolumeID
        parametersRigid["useRigid"] = True
        parametersRigid["initializeTransformMode"] = "useGeometryAlign"
        parametersRigid["samplingPercentage"] = 0.0005
        parametersRigid["minimumStepLength"] = 0.001
        parametersRigid["maximumStepLength"] = 15 # Start with long-range translations
        parametersRigid["relaxationFactor"] = 0.8 # Relax quickly
        parametersRigid["translationScale"] = 1000000 # Suppress rotation

        # Set output transform
        try:
            igrtToPlanningTransformNode = slicer.util.getNode(self.igrtToPlanningTransformName)
        except:
            igrtToPlanningTransformNode = slicer.vtkMRMLLinearTransformNode()
            slicer.mrmlScene.AddNode(igrtToPlanningTransformNode)
            igrtToPlanningTransformNode.SetName(self.igrtToPlanningTransformName)
        parametersRigid["linearTransform"] = igrtToPlanningTransformNode.GetID()

        # Runs the brainsfit registration
        brainsFit = slicer.modules.brainsfit
        cliBrainsFitRigidNode = None
        cliBrainsFitRigidNode = slicer.cli.run(brainsFit, None, parametersRigid)

        waitCount = 0
        while cliBrainsFitRigidNode.GetStatusString() != 'Completed' and waitCount < 200:
            slicer.app.processEvents()
            time.sleep(0.1)
            logging.info(f"Registering planning volume to IGRT volume... iteration {waitCount}")
            waitCount += 1
        logging.info("Rigid registration completed")
        qt.QApplication.restoreOverrideCursor()

        if not igrtToPlanningTransformNode:
            logging.error("Registration failed: transform is None")
            return None
        
        # Apply to planning volume
        # planningNode = slicer.mrmlScene.GetNodeByID(planningVolumeID)
        # planningNode.SetAndObserveTransformNodeID(igrtToPlanningTransformNode.GetID())

        return igrtToPlanningTransformNode

    except Exception as e:
        import traceback
        traceback.print_exc()
        qt.QApplication.restoreOverrideCursor()
        return None

  # ---------------------------------------------------------------------------
  def registerPlanningToIGRTLandmark(self, planningFiducialListID, igrtFiducialListID):
    try:
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      parametersFiducial = {}
      parametersFiducial["fixedLandmarks"] = igrtFiducialListID
      parametersFiducial["movingLandmarks"] = planningFiducialListID

      # Create linear transform which will store the registration transform
      try:
        igrtToPlanningTransformNode = slicer.util.getNode(self.igrtToPlanningTransformName)
      except:
        igrtToPlanningTransformNode = slicer.vtkMRMLLinearTransformNode()
        slicer.mrmlScene.AddNode(igrtToPlanningTransformNode)
        igrtToPlanningTransformNode.SetName(self.igrtToPlanningTransformName)
      parametersFiducial["saveTransform"] = igrtToPlanningTransformNode.GetID()
      parametersFiducial["transformType"] = "Rigid"

      # Run fiducial registration
      fiducialRegistration = slicer.modules.fiducialregistration
      cliFiducialRegistrationRigidNode = None
      cliFiducialRegistrationRigidNode = slicer.cli.run(fiducialRegistration, None, parametersFiducial)

      waitCount = 0
      while cliFiducialRegistrationRigidNode.GetStatusString() != 'Completed' and waitCount < 200:
         slicer.app.processEvents()
         time.sleep(0.1)
         logging.info(f"Registering planning volume to IGRT volume... iteration {waitCount}")
         waitCount += 1
      logging.info("Rigid registration finished")
      qt.QApplication.restoreOverrideCursor()

      if cliFiducialRegistrationRigidNode.GetStatusString() != 'Completed':
        slicer.util.errorDisplay("Registration failed.")
        return None

      # Apply transform to planning fiducials
      planningFiducialsNode = slicer.mrmlScene.GetNodeByID(planningFiducialListID)
      planningFiducialsNode.SetAndObserveTransformNodeID(igrtToPlanningTransformNode.GetID())

      return [igrtToPlanningTransformNode, cliFiducialRegistrationRigidNode.GetParameterAsString('rms')]

    except Exception as e:
      import traceback
      traceback.print_exc()

  # ---------------------------------------------------------------------------
  def registerMeasuredToIGRT(self, measuredFiducialListID, igrtFiducialListID):
    try:
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      parametersFiducial = {}
      parametersFiducial["fixedLandmarks"] = igrtFiducialListID
      parametersFiducial["movingLandmarks"] = measuredFiducialListID

      # Create linear transform which will store the registration transform
      try:
        igrtToMeasuredTransformNode = slicer.util.getNode(self.igrtToMeasuredTransformName)
      except:
        igrtToMeasuredTransformNode = slicer.vtkMRMLLinearTransformNode()
        slicer.mrmlScene.AddNode(igrtToMeasuredTransformNode)
        igrtToMeasuredTransformNode.SetName(self.igrtToMeasuredTransformName)
      parametersFiducial["saveTransform"] = igrtToMeasuredTransformNode.GetID()
      parametersFiducial["transformType"] = "Rigid"

      # Run fiducial registration
      fiducialRegistration = slicer.modules.fiducialregistration
      cliFiducialRegistrationRigidNode = None
      cliFiducialRegistrationRigidNode = slicer.cli.run(fiducialRegistration, None, parametersFiducial)

      waitCount = 0
      while cliFiducialRegistrationRigidNode.GetStatusString() != 'Completed' and waitCount < 200:
         slicer.app.processEvents()
         time.sleep(0.1)
         logging.info(f"Registering MEASURED to IGRT volume... ({waitCount})")
         waitCount += 1
      logging.info("Figudical registration finished")
      qt.QApplication.restoreOverrideCursor()
      
      if cliFiducialRegistrationRigidNode.GetStatusString() != 'Completed':
        slicer.util.errorDisplay("Registration failed.")
        return None

      # Apply transform to MEASURED fiducials
      igrtFiducialsNode = slicer.mrmlScene.GetNodeByID(measuredFiducialListID)
      igrtFiducialsNode.SetAndObserveTransformNodeID(igrtToMeasuredTransformNode.GetID())

      return cliFiducialRegistrationRigidNode.GetParameterAsString('rms')
    except Exception as e:
      import traceback
      traceback.print_exc()
  
  # ---------------------------------------------------------------------------
  def registerMeasuredToIGRTAutomatic(self, measuredVolumeID, igrtVolumeID):
    try:
      qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
      parametersRigid = {}
      parametersRigid["fixedVolume"] = igrtVolumeID
      parametersRigid["movingVolume"] = measuredVolumeID
      parametersRigid["useRigid"] = True
      parametersRigid["initializeTransformMode"] = "useGeometryAlign"
      parametersRigid["samplingPercentage"] = 0.0005
      parametersRigid["minimumStepLength"] = 0.0001
      parametersRigid["maximumStepLength"] = 15 # Start with long-range translations
      parametersRigid["relaxationFactor"] = 0.8 # Relax quickly
      parametersRigid["translationScale"] = 1000000 # Suppress rotation

      try:
        igrtToMeasuredTransformNode = slicer.util.getNode(self.igrtToMeasuredTransformName)
      except:
        igrtToMeasuredTransformNode = slicer.vtkMRMLLinearTransformNode()
        slicer.mrmlScene.AddNode(igrtToMeasuredTransformNode)
        igrtToMeasuredTransformNode.SetName(self.igrtToMeasuredTransformName)
      parametersRigid["linearTransform"] = igrtToMeasuredTransformNode.GetID()

      # Runs the brainsfit registration
      brainsFit = slicer.modules.brainsfit
      cliBrainsFitRigidNode = None
      cliBrainsFitRigidNode = slicer.cli.run(brainsFit, None, parametersRigid)

      waitCount = 0
      while cliBrainsFitRigidNode.GetStatusString() != 'Completed' and waitCount < 200:
          slicer.app.processEvents()
          time.sleep(0.1)
          logging.info(f"Registering MEASURED to IGRT volume... iteration {waitCount}")
          waitCount += 1
      logging.info("Rigid registration completed")
      qt.QApplication.restoreOverrideCursor()

      if not igrtToMeasuredTransformNode:
          logging.error("Registration failed: transform is None")
          return None

      return igrtToMeasuredTransformNode

    except Exception as e:
      import traceback
      traceback.print_exc()
      qt.QApplication.restoreOverrideCursor()
      return None
  
  # ---------------------------------------------------------------------------
  def loadPdd(self, fileName):
    if fileName == None or fileName == '':
      logging.error('Empty PDD file name')
      return False

    readFile = open(fileName, 'r')
    lines = readFile.readlines()
    doseTable = numpy.zeros([len(lines), 2]) # 2 columns

    rowCounter = 0
    for line in lines:
      firstValue, endOfLine = line.partition(',')[::2]
      if endOfLine == '':
        logging.error("File formatted incorrectly")
        return False
      valueOne = float(firstValue)
      doseTable[rowCounter, 1] = valueOne
      secondValue, lineEnd = endOfLine.partition('\n')[::2]
      if (secondValue == ''):
        logging.error("Two values are required per line in the file")
        return False
      valueTwo = float(secondValue)
      doseTable[rowCounter, 0] = secondValue
      # logging.debug('PDD row ' + rowCounter + ': ' + firstValue + ', ' + secondValue) # For testing
      rowCounter += 1

    logging.info("Pdd data successfully loaded from file '" + fileName + "'")
    self.pddDataArray = doseTable
    return True

  # ---------------------------------------------------------------------------
  def getMeanDeltaROfCentralCylinder(self, calibrationVolumeNodeID, centralRadiusMm):
    # Format of output array: the following values are provided for each slice:
    # depth (cm), mean R1/R2 on the slice at depth, std.dev. of R1/R2
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))

    calibrationVolume = slicer.util.getNode(calibrationVolumeNodeID)
    calibrationVolumeImageData = calibrationVolume.GetImageData()

    # Get image properties needed for the calculation
    calibrationVolumeSliceThicknessCm = calibrationVolume.GetSpacing()[2] / 10.0
    if calibrationVolume.GetSpacing()[0] != calibrationVolume.GetSpacing()[1]:
      logging.warning('Image data X and Y spacing differ! This is not supported, the mean R1/R2 data may be skewed')
    calibrationVolumeInPlaneSpacing = calibrationVolume.GetSpacing()[0]

    centralRadiusPixel = int(numpy.ceil(centralRadiusMm / calibrationVolumeInPlaneSpacing))
    if centralRadiusPixel != centralRadiusMm / calibrationVolumeInPlaneSpacing:
      logging.info('Central radius has been rounded up to {0} (original radius is {1}mm = {2}px)'.format(centralRadiusPixel, centralRadiusMm, centralRadiusMm / calibrationVolumeInPlaneSpacing))

    numberOfSlices = calibrationVolumeImageData.GetExtent()[5] - calibrationVolumeImageData.GetExtent()[4] + 1
    centerXCoordinate = (calibrationVolumeImageData.GetExtent()[1] - calibrationVolumeImageData.GetExtent()[0])/2
    centerYCoordinate = (calibrationVolumeImageData.GetExtent()[3] - calibrationVolumeImageData.GetExtent()[2])/2

    # Get image data in numpy array
    calibrationVolumeImageDataAsScalars = calibrationVolumeImageData.GetPointData().GetScalars()
    numpyImageDataArray = numpy_support.vtk_to_numpy(calibrationVolumeImageDataAsScalars)
    numpyImageDataArray = numpy.reshape(numpyImageDataArray, (calibrationVolumeImageData.GetExtent()[1]+1, calibrationVolumeImageData.GetExtent()[3]+1, calibrationVolumeImageData.GetExtent()[5]+1), 'F')

    deltaROfCentralCylinderTable = numpy.zeros((numberOfSlices, 3))
    sliceNumber = 0
    z = calibrationVolumeImageData.GetExtent()[5]
    zMin = calibrationVolumeImageData.GetExtent()[4]
    while z  >= zMin:
      totalPixels = 0
      totalDeltaR = 0
      listOfDeltaRValues = []
      meanDeltaR = 0

      for y in range(floor(centerYCoordinate - centralRadiusPixel + 0.5), ceil(centerYCoordinate + centralRadiusPixel + 0.5)):
        for x in range(floor(centerXCoordinate - centralRadiusPixel + 0.5), ceil(centerXCoordinate + centralRadiusPixel + 0.5)):
          distanceOfX = abs(x - centerXCoordinate)
          distanceOfY = abs(y - centerYCoordinate)
          if ((distanceOfX + distanceOfY) <= centralRadiusPixel) or ((pow(distanceOfX, 2) + pow(distanceOfY, 2)) <= pow(centralRadiusPixel, 2)):
            currentDeltaR = numpyImageDataArray[x, y, z]
            listOfDeltaRValues.append(currentDeltaR)
            totalDeltaR = totalDeltaR + currentDeltaR
            totalPixels+=1

      meanDeltaR = totalDeltaR / totalPixels
      standardDeviationDeltaR	= 0
      for currentDeltaRValue in range(totalPixels):
        standardDeviationDeltaR += pow((listOfDeltaRValues[currentDeltaRValue] - meanDeltaR), 2)
      standardDeviationDeltaR = sqrt(standardDeviationDeltaR / totalPixels)
      deltaROfCentralCylinderTable[sliceNumber, 0] = sliceNumber * calibrationVolumeSliceThicknessCm
      deltaROfCentralCylinderTable[sliceNumber, 1] = meanDeltaR
      deltaROfCentralCylinderTable[sliceNumber, 2] = standardDeviationDeltaR
      sliceNumber += 1
      z -= 1

    qt.QApplication.restoreOverrideCursor()
    logging.info('CALIBRATION data has been successfully parsed with averaging radius {0}mm ({1}px)'.format(centralRadiusMm, centralRadiusPixel))
    self.calibrationDataArray = deltaROfCentralCylinderTable
    return True

  # ---------------------------------------------------------------------------
  def sampleCalibrationAlongLine(self, measuredVolumeNode, rulerNode, samplingRadiusMm, numberOfSamples=100):
    import numpy as np
    
    try:
        # Get line endpoints
        startPoint_RAS = [0, 0, 0]
        endPoint_RAS = [0, 0, 0]
        rulerNode.GetNthControlPointPosition(0, startPoint_RAS)
        rulerNode.GetNthControlPointPosition(1, endPoint_RAS)
        
        # Calculate line direction and length
        lineVector = np.array(endPoint_RAS) - np.array(startPoint_RAS)
        lineLength = np.linalg.norm(lineVector)
        lineDirection = lineVector / lineLength
        
        # Get two perpendicular directions for radius sampling
        if abs(lineDirection[2]) < 0.9:
            perp1 = np.cross(lineDirection, [0, 0, 1])
        else:
            perp1 = np.cross(lineDirection, [1, 0, 0])
        perp1 = perp1 / np.linalg.norm(perp1)
        perp2 = np.cross(lineDirection, perp1)
        perp2 = perp2 / np.linalg.norm(perp2)
        
        # Get image data and transform
        imageData = measuredVolumeNode.GetImageData()
        rasToIJK = vtk.vtkMatrix4x4()
        measuredVolumeNode.GetRASToIJKMatrix(rasToIJK)
        
        # Sample along the line
        calibrationData = []
        
        for i in range(numberOfSamples):
            # Position along the line
            t = i / (numberOfSamples - 1.0)
            centerPoint_RAS = np.array(startPoint_RAS) + t * lineVector
            depth_cm = t * lineLength / 10.0  # Convert mm to cm
            
            # Sample in a circle around this point
            numRadialSamples = 12  # Number of samples around the circle
            numRadiusSamples = 5   # Number of samples along the radius
            values = []
            
            for radiusStep in range(1, numRadiusSamples + 1):
                currentRadius = samplingRadiusMm * (radiusStep / numRadiusSamples)
                
                for angle in np.linspace(0, 2*np.pi, numRadialSamples, endpoint=False):
                    # Calculate offset point
                    offset = currentRadius * (np.cos(angle) * perp1 + np.sin(angle) * perp2)
                    samplePoint_RAS = centerPoint_RAS + offset
                    
                    # Convert to IJK coordinates
                    point_IJK = [0, 0, 0, 1]
                    rasToIJK.MultiplyPoint([samplePoint_RAS[0], samplePoint_RAS[1], samplePoint_RAS[2], 1.0], point_IJK)
                    
                    # Get voxel value with interpolation
                    i_idx = int(round(point_IJK[0]))
                    j_idx = int(round(point_IJK[1]))
                    k_idx = int(round(point_IJK[2]))
                    
                    dims = imageData.GetDimensions()
                    if (0 <= i_idx < dims[0] and 0 <= j_idx < dims[1] and 0 <= k_idx < dims[2]):
                        value = imageData.GetScalarComponentAsDouble(i_idx, j_idx, k_idx, 0)
                        values.append(value)
            
            # Average all sampled values at this depth
            if len(values) > 0:
                meanValue = np.mean(values)
                calibrationData.append([depth_cm, meanValue])
        
        # Store the calibration data
        self.calibrationDataArray = np.array(calibrationData)
        
        logging.info(f'Line sampling complete: {len(calibrationData)} points sampled')
        return True
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        logging.error(f'Line sampling failed: {str(e)}')
        return False

  # ---------------------------------------------------------------------------
  def alignPddToCalibration(self):
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
    error = -1.0

    # Check the input arrays
    if self.pddDataArray.size == 0 or self.calibrationDataArray.size == 0:
      logging.error('Pdd or calibration data is empty')
      return error

    # Discard values of 0 from both ends of the data (it is considered invalid)
    self.calibrationDataCleanedArray = self.calibrationDataArray
    calibrationCleanedNumberOfRows = self.calibrationDataCleanedArray.shape[0]
    while self.calibrationDataCleanedArray[0,1] == 0:
      self.calibrationDataCleanedArray = numpy.delete(self.calibrationDataCleanedArray, 0, 0)
    calibrationCleanedNumberOfRows = self.calibrationDataCleanedArray.shape[0]
    while self.calibrationDataCleanedArray[calibrationCleanedNumberOfRows-1,1] == 0:
      self.calibrationDataCleanedArray = numpy.delete(self.calibrationDataCleanedArray, calibrationCleanedNumberOfRows-1, 0)
      calibrationCleanedNumberOfRows = self.calibrationDataCleanedArray.shape[0]

    # Remove outliers from calibration array
    self.calibrationDataCleanedArray = self.removeOutliersFromArray(self.calibrationDataCleanedArray, 5, 10, 0.0075)[0]

    # Do initial scaling of the calibration array based on the maximum values
    maxPdd = self.findMaxValueInArray(self.pddDataArray)
    maxCalibration = self.findMaxValueInArray(self.calibrationDataCleanedArray)
    initialScaling = maxPdd / maxCalibration
    # logging.debug('Initial scaling factor {0:.4f}'.format(initialScaling))

    # Create the working structures
    self.minimizer = vtk.vtkAmoebaMinimizer()
    self.minimizer.SetFunction(curveAlignmentCalibrationFunction)
    self.minimizer.SetParameterValue("xTrans",0)
    self.minimizer.SetParameterScale("xTrans",2)
    self.minimizer.SetParameterValue("yScale",initialScaling)
    self.minimizer.SetParameterScale("yScale",0.1)
    self.minimizer.SetParameterValue("yTrans",0)
    self.minimizer.SetParameterScale("yTrans",0.2)
    self.minimizer.SetMaxIterations(50)

    self.minimizer.Minimize()
    error = self.minimizer.GetFunctionValue()
    xTrans = self.minimizer.GetParameterValue("xTrans")
    yScale = self.minimizer.GetParameterValue("yScale")
    yTrans = self.minimizer.GetParameterValue("yTrans")

    # Create aligned array
    self.createAlignedCalibrationArray(xTrans, yScale, yTrans)

    qt.QApplication.restoreOverrideCursor()
    logging.info('CALIBRATION successfully aligned with PDD with error={0:.2f} and parameters xTrans={1:.2f}, yScale={2:.2f}, yTrans={3:.2f}'.format(error, xTrans, yScale, yTrans))
    return [error, xTrans, yScale, yTrans]

  # ---------------------------------------------------------------------------
  def createAlignedCalibrationArray(self, xTrans, yScale, yTrans):
    # Create aligned array used for computation
    self.calibrationDataAlignedArray = numpy.zeros([self.pddDataArray.shape[0], 2])
    interpolator = vtk.vtkPiecewiseFunction()
    self.populateInterpolatorForParameters(interpolator, xTrans, 1, 0)
    interpolatorRange = interpolator.GetRange()
    sumSquaredDifference = 0.0
    calibrationAlignedRowIndex = -1
    pddNumberOfRows = self.pddDataArray.shape[0]
    for pddRowIndex in range(pddNumberOfRows):
      pddCurrentDepth = self.pddDataArray[pddRowIndex, 0]
      if pddCurrentDepth >= interpolatorRange[0] and pddCurrentDepth <= interpolatorRange[1]:
        calibrationAlignedRowIndex += 1
        self.calibrationDataAlignedArray[calibrationAlignedRowIndex, 0] = pddCurrentDepth
        self.calibrationDataAlignedArray[calibrationAlignedRowIndex, 1] = interpolator.GetValue(pddCurrentDepth)
      else:
        # If the Pdd depth value is out of range then delete the last row (it will never be set, but we need to remove the zeros from the end)
        self.calibrationDataAlignedArray = numpy.delete(self.calibrationDataAlignedArray, self.calibrationDataAlignedArray.shape[0]-1, 0)

    # Create aligned array used for display (visual alignment)
    self.calibrationDataAlignedToDisplayArray = numpy.zeros([self.pddDataArray.shape[0], 2])
    interpolator = vtk.vtkPiecewiseFunction()
    self.populateInterpolatorForParameters(interpolator, xTrans, yScale, yTrans)
    interpolatorRange = interpolator.GetRange()
    sumSquaredDifference = 0.0
    calibrationAlignedRowIndex = -1
    pddNumberOfRows = self.pddDataArray.shape[0]
    for pddRowIndex in range(pddNumberOfRows):
      pddCurrentDepth = self.pddDataArray[pddRowIndex, 0]
      if pddCurrentDepth >= interpolatorRange[0] and pddCurrentDepth <= interpolatorRange[1]:
        calibrationAlignedRowIndex += 1
        self.calibrationDataAlignedToDisplayArray[calibrationAlignedRowIndex, 0] = pddCurrentDepth
        self.calibrationDataAlignedToDisplayArray[calibrationAlignedRowIndex, 1] = interpolator.GetValue(pddCurrentDepth)
      else:
        # If the Pdd depth value is out of range then delete the last row (it will never be set, but we need to remove the zeros from the end)
        self.calibrationDataAlignedToDisplayArray = numpy.delete(self.calibrationDataAlignedToDisplayArray, self.calibrationDataAlignedToDisplayArray.shape[0]-1, 0)

  # ---------------------------------------------------------------------------
  def removeOutliersFromArray(self, arrayToClean, outlierThreshold, maxNumberOfOutlierIterations, minimumMeanDifferenceInFractionOfMaxValueThreshold):
    # Removes outliers starting from the two ends of a function stored in an array
    # The input array has to have two columns, the first column containing the X values, the second the Y values
    # Parameters:
    #   - outlierThreshold: Multiplier of mean of differences. If a value is more than this much different to its neighbor than it is an outlier
    #   - minimumMeanDifferenceInFractionOfMaxValueThreshold: The array is considered not to contain outliers if the mean differences are less than the maximum value multiplied by this value
    numberOfFoundOutliers = -1
    numberOfIterations = 0

    # Compute average difference between two adjacent points. Go from both ends of the curve,
    # and throw away points that have a difference bigger than the computed average multiplied by N.
    # Do this until no points are thrown away in an iteration OR there are no points left (error)
    # OR the average difference is small enough
    numberOfRows = arrayToClean.shape[0]
    while numberOfIterations < maxNumberOfOutlierIterations and numberOfFoundOutliers != 0 and numberOfRows > 0:
      maxValue = self.findMaxValueInArray(arrayToClean)
      meanDifference = self.computeMeanDifferenceOfNeighborsForArray(arrayToClean)
      # logging.debug('Outlier removal iteration {0}: MeanDifference={1:.2f} (fraction of max value: {2:.4f})'.format(numberOfIterations, meanDifference, meanDifference/maxValue))
      # logging.debug('  Difference at edges: first={0:.2f}  last={1:.2f}'.format(abs(arrayToClean[0,1] - arrayToClean[1,1]), abs(arrayToClean[numberOfRows-1,1] - arrayToClean[numberOfRows-2,1])))
      if meanDifference < maxValue * minimumMeanDifferenceInFractionOfMaxValueThreshold:
        # logging.debug('  MaxValue: {0:.2f} ({1:.4f}), finishing outlier search'.format(maxValue,maxValue*minimumMeanDifferenceInFractionOfMaxValueThreshold))
        break
      numberOfFoundOutliers = 0
      # Remove outliers from the beginning
      while abs(arrayToClean[0,1] - arrayToClean[1,1]) > meanDifference * outlierThreshold:
        # logging.debug('  Deleted first: {0:.2f},{0:.2f}  difference={0:.2f}'.format(arrayToClean[0,0], arrayToClean[0,1], abs(arrayToClean[0,1] - arrayToClean[1,1])))
        arrayToClean = numpy.delete(arrayToClean, 0, 0)
        numberOfFoundOutliers += 1
      # Remove outliers from the end
      numberOfRows = arrayToClean.shape[0]
      while abs(arrayToClean[numberOfRows-1,1] - arrayToClean[numberOfRows-2,1]) > meanDifference * outlierThreshold:
        # logging.debug('  Deleted last: {0:.2f},{0:.2f}  difference={0:.2f}'.format(arrayToClean[numberOfRows-1,0], arrayToClean[numberOfRows-1,1], abs(arrayToClean[numberOfRows-1,1] - arrayToClean[numberOfRows-2,1])))
        arrayToClean = numpy.delete(arrayToClean, numberOfRows-1, 0)
        numberOfRows = arrayToClean.shape[0]
        numberOfFoundOutliers += 1
      numberOfRows = arrayToClean.shape[0]
      numberOfIterations += 1

    return [arrayToClean, numberOfFoundOutliers]

  # ---------------------------------------------------------------------------
  def computeMeanDifferenceOfNeighborsForArray(self, array):
    numberOfValues = array.shape[0]
    sumDifferences = 0
    for index in range(numberOfValues-1):
      sumDifferences += abs(array[index, 1] - array[index+1, 1])
    return sumDifferences / (numberOfValues-1)

  # ---------------------------------------------------------------------------
  def findMaxValueInArray(self, array):
    numberOfValues = array.shape[0]
    maximumValue = -1
    for index in range(numberOfValues):
      if array[index, 1] > maximumValue:
        maximumValue = array[index, 1]
    return maximumValue

  # ---------------------------------------------------------------------------
  def populateInterpolatorForParameters(self, interpolator, xTrans, yScale, yTrans):
    calibrationNumberOfRows = self.calibrationDataCleanedArray.shape[0]
    for calibrationRowIndex in range(calibrationNumberOfRows):
      xTranslated = self.calibrationDataCleanedArray[calibrationRowIndex, 0] + xTrans
      yScaled = self.calibrationDataCleanedArray[calibrationRowIndex, 1] * yScale
      yStretched = yScaled + yTrans
      interpolator.AddPoint(xTranslated, yStretched)

  # ---------------------------------------------------------------------------
  def computeDoseForMeasuredData(self, rdf, monitorUnits):
    self.calculatedDose = numpy.zeros(self.pddDataArray.shape)
    pddNumberOfRows = self.pddDataArray.shape[0]
    for pddRowIndex in range(pddNumberOfRows):
      self.calculatedDose[pddRowIndex, 0] = self.pddDataArray[pddRowIndex, 0]
      self.calculatedDose[pddRowIndex, 1] = self.pddDataArray[pddRowIndex, 1] * rdf * monitorUnits / 10000.0
    return True

  # ---------------------------------------------------------------------------
  def createDeltaRVsDoseFunction(self, pddRangeMin=-1000, pddRangeMax=1000):
    # Create interpolator for aligned calibration function to allow getting the values for the
    # depths present in the calculated dose function
    interpolator = vtk.vtkPiecewiseFunction()
    calibrationAlignedNumberOfRows = self.calibrationDataAlignedArray.shape[0]
    for calibrationRowIndex in range(calibrationAlignedNumberOfRows):
      currentDose = self.calibrationDataAlignedArray[calibrationRowIndex, 0]
      currentDeltaR = self.calibrationDataAlignedArray[calibrationRowIndex, 1]
      interpolator.AddPoint(currentDose, currentDeltaR)
    interpolatorRange = interpolator.GetRange()

    # Get the R1/R2 and the dose values from the aligned calibration function and the calculated dose
    self.deltaRVsDoseFunction = numpy.zeros(self.calculatedDose.shape)
    doseNumberOfRows = self.calculatedDose.shape[0]
    for doseRowIndex in range(doseNumberOfRows):
      # Reverse the function so that smallest dose comes first (which decreases with depth)
      currentDepth = self.calculatedDose[doseRowIndex, 0]
      if currentDepth >= interpolatorRange[0] and currentDepth <= interpolatorRange[1] and currentDepth >= pddRangeMin and currentDepth <= pddRangeMax:
        self.deltaRVsDoseFunction[doseNumberOfRows-doseRowIndex-1, 0] = interpolator.GetValue(currentDepth)
        self.deltaRVsDoseFunction[doseNumberOfRows-doseRowIndex-1, 1] = self.calculatedDose[doseRowIndex, 1]
      else:
        # If the depth value is out of range then delete the last row (it will never be set, but we need to remove the zeros from the end)
        self.deltaRVsDoseFunction = numpy.delete(self.deltaRVsDoseFunction, doseNumberOfRows-doseRowIndex-1, 0)

  # ---------------------------------------------------------------------------
  def fitCurveToDeltaRVsDoseFunctionArray(self, orderOfFittedPolynomial):
    # Fit polynomial on the cleaned R1/R2 vs dose function array
    deltaRVsDoseNumberOfRows = self.deltaRVsDoseFunction.shape[0]
    deltaRData = numpy.zeros((deltaRVsDoseNumberOfRows))
    doseData = numpy.zeros((deltaRVsDoseNumberOfRows))
    for rowIndex in range(deltaRVsDoseNumberOfRows):
      deltaRData[rowIndex] = self.deltaRVsDoseFunction[rowIndex, 0]
      doseData[rowIndex] = self.deltaRVsDoseFunction[rowIndex, 1]
    fittingResult = numpy.polyfit(deltaRData, doseData, orderOfFittedPolynomial, None, True)
    self.calibrationPolynomialCoefficients = fittingResult[0]
    self.fittingResiduals = fittingResult[1]
    logging.info('Coefficients of the fitted polynomial (highest order first): ' + repr(self.calibrationPolynomialCoefficients.tolist()))
    logging.info('  Fitting residuals: ' + repr(self.fittingResiduals[0]))
    return self.fittingResiduals

  # ---------------------------------------------------------------------------
  def exportCalibrationToCSV(self):
    import csv, os
    from time import gmtime, strftime

    directory = qt.QFileDialog.getExistingDirectory(None, "Select directory to save calibration data", slicer.app.temporaryPath)
    if not directory:
        slicer.util.delayDisplay("Export cancelled.")
        return

    timestamp = strftime("%Y%m%d_%H%M%S", gmtime())
    curveFile = os.path.join(directory, f"{timestamp}_R1R2VsDosePoints.csv")
    coeffFile = os.path.join(directory, f"{timestamp}_CalibrationPolynomialCoefficients.csv")

    # R1/R2 vs. Dose
    if self.deltaRVsDoseFunction is not None:
        with open(curveFile, 'w', newline='') as fp:
            csvWriter = csv.writer(fp, delimiter=',', lineterminator='\n')
            data = [['R1/R2','Dose']]
            for deltaRVsDosePoint in self.deltaRVsDoseFunction:
                data.append(deltaRVsDosePoint)
            csvWriter.writerows(data)

    # Assemble file name for polynomial coefficients
    if hasattr(self, 'calibrationPolynomialCoefficients'):
        with open(coeffFile, 'w', newline='') as fp:
            csvWriter = csv.writer(fp, delimiter=',', lineterminator='\n')
            data = [['Order','Coefficient']]
            numOfOrders = len(self.calibrationPolynomialCoefficients)
            # Highest order first in the coeffiicnets list
            for orderIndex in range(numOfOrders):
                data.append([numOfOrders-orderIndex-1, self.calibrationPolynomialCoefficients[orderIndex]])
            if hasattr(self, 'fittingResiduals'):
                data.append(['Residuals', self.fittingResiduals[0]])
            csvWriter.writerows(data)

    return (f"Files saved:\n{curveFile}\n{coeffFile}")

  # ---------------------------------------------------------------------------
  def calibrate(self, measuredVolumeID):
    qt.QApplication.setOverrideCursor(qt.QCursor(qt.Qt.BusyCursor))
    import time
    start = time.time()

    measuredVolume = slicer.util.getNode(measuredVolumeID)
    calibratedVolume = slicer.vtkMRMLScalarVolumeNode()
    calibratedVolumeName = measuredVolume.GetName() + '_Calibrated'
    calibratedVolumeName = slicer.mrmlScene.GenerateUniqueName(calibratedVolumeName)
    calibratedVolume.SetName(calibratedVolumeName)
    slicer.mrmlScene.AddNode(calibratedVolume)
    measuredImageDataCopy = vtk.vtkImageData()
    measuredImageDataCopy.DeepCopy(measuredVolume.GetImageData())
    calibratedVolume.SetAndObserveImageData(measuredImageDataCopy)
    calibratedVolume.CopyOrientation(measuredVolume)
    if measuredVolume.GetParentTransformNode() != None:
      calibratedVolume.SetAndObserveTransformNodeID(measuredVolume.GetParentTransformNode().GetID())

    # Apply the fitted polynomial voxel-wise using NumPy directly
    try:
      measuredArray = slicer.util.arrayFromVolume(calibratedVolume)
      calibratedArray = numpy.polyval(self.calibrationPolynomialCoefficients, measuredArray)
      slicer.util.updateVolumeFromArray(calibratedVolume, calibratedArray)
    except Exception as e:
      logging.error('Calibration failed: {0}'.format(str(e)))
      slicer.mrmlScene.RemoveNode(calibratedVolume)
      qt.QApplication.restoreOverrideCursor()
      return None

    end = time.time()
    qt.QApplication.restoreOverrideCursor()
    logging.info('Calibration of MEASURED volume is successful (time: {0})'.format(end - start))
    return calibratedVolume
  
  # ---------------------------------------------------------------------------
  def exportLineProfileToCSV(self, lineProfileData):
    import csv, os
    from time import gmtime, strftime

    directory = qt.QFileDialog.getExistingDirectory(None, "Select directory to save line profile data", slicer.app.temporaryPath)
    if not directory:
        slicer.util.delayDisplay("Export cancelled.")
        return

    timestamp = strftime("%Y%m%d_%H%M%S", gmtime())
    profileFile = os.path.join(directory, f"{timestamp}_LineProfile.csv")

    # Line Profile data
    if lineProfileData is not None and len(lineProfileData) > 0:
        with open(profileFile, 'w', newline='') as fp:
            csvWriter = csv.writer(fp, delimiter=',', lineterminator='\n')
            data = [['Position (mm)', 'Value']]
            for row in lineProfileData:
                data.append(row)
            csvWriter.writerows(data)
        return f"File saved:\n{profileFile}"
    return "Export failed: no data"
#
# Function to minimize for the calibration curve alignment
#
def curveAlignmentCalibrationFunction():
  # Get logic instance
  global gelDosimetryLogicInstanceGlobal
  logic = gelDosimetryLogicInstanceGlobal

  # Transform experimental calibration curve with the current values provided by the minimizer and
  # create piecewise function from the transformed calibration curve to be able to compare with the Pdd
  xTrans = logic.minimizer.GetParameterValue("xTrans")
  yScale = logic.minimizer.GetParameterValue("yScale")
  yTrans = logic.minimizer.GetParameterValue("yTrans")
  interpolator = vtk.vtkPiecewiseFunction()
  logic.populateInterpolatorForParameters(interpolator, xTrans, yScale, yTrans)
  interpolatorRange = interpolator.GetRange()
  # Compute similarity between the Pdd and the transformed calibration curve
  pddNumberOfRows = logic.pddDataArray.shape[0]
  sumSquaredDifference = 0.0
  for pddRowIndex in range(pddNumberOfRows):
    pddCurrentDepth = logic.pddDataArray[pddRowIndex, 0]
    pddCurrentDose = logic.pddDataArray[pddRowIndex, 1]
    difference = pddCurrentDose - interpolator.GetValue(pddCurrentDepth)
    if pddCurrentDepth < interpolatorRange[0] or pddCurrentDepth > interpolatorRange[1]:
      pass # Don't count the parts outside the range of the actual transformed calibration curve
    else:
      sumSquaredDifference += difference ** 2

  # logging.debug('Iteration: {0:2}  xTrans: {1:6.2f}  yScale: {2:6.2f}  yTrans: {3:6.2f}    error: {4:.2f}'.format(logic.minimizer.GetIterations(), xTrans, yScale, yTrans, sumSquaredDifference))
  logic.minimizer.SetFunctionValue(sumSquaredDifference)

# Global variable holding the logic instance for the calibration curve minimizer function
gelDosimetryLogicInstanceGlobal = None

# Notes:
# Code snippet to reload logic
# GelDosimetryAnalysisLogic = reload(GelDosimetryAnalysisLogic)