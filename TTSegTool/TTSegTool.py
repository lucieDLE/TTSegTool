import os
import qt
import unittest
import logging
from csv import DictReader, DictWriter
from pathlib import Path

from CommonUtilities import utility
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

#
# TTSegToolSliceletWidget
#
class TTSegToolSliceletWidget:
  def __init__(self, parent=None):
    try:
      parent
      self.parent = parent

    except Exception as e:
      import traceback
      traceback.print_exc()
      logging.error("There is no parent to TTSegToolSliceletWidget!")

class SliceletMainFrame(qt.QDialog):
  def setSlicelet(self, slicelet):
    self.slicelet = slicelet

  def hideEvent(self, event):
    self.slicelet.disconnect()

    # import gc
    # refs = gc.get_referrers(self.slicelet)
    # if len(refs) > 1:
    #   # logging.debug('Stuck slicelet references (' + repr(len(refs)) + '):\n' + repr(refs))
    #   pass

    # slicer.ttSegToolInstance = None
    # self.slicelet = None
    # self.deleteLater()

class TTSegToolSlicelet(VTKObservationMixin):
  def __init__(self, parent, developerMode=False, resourcePath=None):
    VTKObservationMixin.__init__(self)
    slicer.mrmlScene.Clear()
    self.logic = None
    self.parent = parent
    self.parent.setLayout(qt.QHBoxLayout())
    self.layout = self.parent.layout()
    self.layout.setMargin(0)
    self.layout.setSpacing(0)

    self.sliceletPanel = qt.QFrame(self.parent)
    self.sliceletPanelLayout = qt.QVBoxLayout(self.sliceletPanel)
    self.sliceletPanelLayout.setMargin(4)
    self.sliceletPanelLayout.setSpacing(0)
    self.layout.addWidget(self.sliceletPanel,0)

    self.ui = None
    self.setDefaultParamaters()
    if resourcePath is not None:
      uiWidget = slicer.util.loadUI(resourcePath)
      self.layout.addWidget(uiWidget)
      self.ui = slicer.util.childWidgetVariables(uiWidget)
      self.setupConnections()

    self.layoutWidget = slicer.qMRMLLayoutWidget() 
    self.layoutWidget.setMRMLScene(slicer.mrmlScene)
    self.parent.layout().addWidget(self.layoutWidget,2)
    self.onViewSelect(7)
    
    # setup self connections
    self.setupLayoutConnections()

    self.parent.show()

  #------------------------------------------------------------------------------
  def disconnect(self):
    logging.info('Disconnecting something')

  #------------------------------------------------------------------------------
  def setDefaultParamaters(self):
    self.path_to_images = None
    self.path_to_image_list = None
    self.path_to_segmentations = None
    self.image_node = None
    self.initData()
    self.updateNavigationUI()
  
  def updatePatchesTable(self, ijk=None, healthy_patch = False, clearTable = False):
    logging.info("{} {} {}".format(len(self.image_list), self.current_ind, self.path_to_images))
    if len(self.image_list) == 0 or \
       self.path_to_images is None or \
        self.current_ind < 0 or self.current_ind >= len(self.image_list):
      logging.warning('Cannot update patches table: Select a valid csv file and point to a correct folder with images')
      return
    
    if clearTable:
      #TODO: Potentially can add a check if there's a file that already has the patches, and load it
      self.ui.imagePatchesTableWidget.clearContents()
      return
    
    if ijk is not None:
      numrows = self.ui.imagePatchesTableWidget.rowCount
      self.ui.imagePatchesTableWidget.insertRow(numrows)
      item = qt.QTableWidgetItem("{}".format(numrows))
      self.ui.imagePatchesTableWidget.setItem(numrows, 0, item)
      item1 = qt.QTableWidgetItem("{},{}".format(ijk[0], ijk[1]))
      self.ui.imagePatchesTableWidget.setItem(numrows, 1, item1)
      item2 = qt.QTableWidgetItem("Healthy" if healthy_patch else "TT")
      self.ui.imagePatchesTableWidget.setItem(numrows, 2, item2)

  #------------------------------------------------------------------------------
  def updateNavigationUI(self):
    if self.ui == None:
      return

    if len(self.image_list) == 0:
      min = 0
      max = 0
      ind = 0
    else:
      min = 1
      ind = self.current_ind + 1
      max = len(self.image_list)

    if self.current_ind >= 0 and self.current_ind < max:
      detailsText = "::: Image {}/{} ::: FILE NAME: {}".format(ind, max, self.image_list[self.current_ind])
    else:
      detailsText = "Image list empty"
    
    self.ui.imagePosLabel.setText("{}/{}".format(ind,max))
    self.ui.imageNavigationScrollBar.setMinimum(min)
    self.ui.imageNavigationScrollBar.setMaximum(max)
    self.ui.imageDetailsLabel.setText(detailsText)  

  #------------------------------------------------------------------------------
  def setupConnections(self):
    self.ui.imageDirButton.connect('directoryChanged(QString)', self.onInputDirChanged)
    self.ui.imageFileButton.clicked.connect(self.openFileNamesDialog)
    self.ui.imageNavigationScrollBar.setTracking(False)
    self.ui.imageNavigationScrollBar.valueChanged.connect(self.onImageIndexChanged)
    self.ui.keepPatchPushButton.clicked.connect(self.onKeepHealthyPatchClicked)
    self.ui.keepPatchTTPushButton.clicked.connect(self.onKeepTTPatchClicked)
    self.ui.delPatchPushButton.clicked.connect(self.onDelPatchClicked)

  #------------------------------------------------------------------------------
  def setupLayoutConnections(self):
    if self.layoutWidget is None:
      logging.warning('Layout widget is not set')
    
    lm = self.layoutWidget.layoutManager()
    sw = lm.sliceWidget('Red')
    self.interactor = sw.interactorStyle().GetInteractor()
    self.interactor.AddObserver(vtk.vtkCommand.LeftButtonPressEvent, self.OnClick)
    self.crosshairNode=slicer.util.getNode('Crosshair')


  #
  # -----------------------
  # Event handler functions
  # -----------------------
  #  
  #------------------------------------------------------------------------------
  def onKeepHealthyPatchClicked(self):
    if len(self.image_list) == 0 or \
       self.path_to_images is None or \
        self.current_ind < 0 or self.current_ind >= len(self.image_list):
      logging.warning('Cannot update patches table: Select a valid csv file and point to a correct folder with images')
      return
    
    row = self.ui.imagePatchesTableWidget.currentRow()
    item = self.ui.imagePatchesTableWidget.item(row, 2)
    if item is not None:
      item.setText("Healthy")
      self.ui.imagePatchesTableWidget.item(row,2).setText("Healthy")

  def onKeepTTPatchClicked(self):
    if len(self.image_list) == 0 or \
       self.path_to_images is None or \
        self.current_ind < 0 or self.current_ind >= len(self.image_list):
      logging.warning('Cannot update patches table: Select a valid csv file and point to a correct folder with images')
      return
    
    row = self.ui.imagePatchesTableWidget.currentRow()
    item = self.ui.imagePatchesTableWidget.item(row, 2)
    if item is not None:
      item.setText("Healthy")
      self.ui.imagePatchesTableWidget.item(row,2).setText("TT")

  def onDelPatchClicked(self):
    if len(self.image_list) == 0 or \
       self.path_to_images is None or \
        self.current_ind < 0 or self.current_ind >= len(self.image_list):
      logging.warning('Cannot update patches table: Select a valid csv file and point to a correct folder with images')
      return
    
    row = self.ui.imagePatchesTableWidget.currentRow()
    logging.info('Removing image patch at position: {}'.format(row))
    self.ui.imagePatchesTableWidget.removeRow(row)

  #------------------------------------------------------------------------------
  def OnClick(self, caller, event):
    if self.interactor is not None and self.crosshairNode is not None:
      def _roundInt(value):
        try:
          return int(round(value))
        except ValueError:
          logging.info('Getting a ValueError during roundupt')
          return 0

      xyz = [0,0,0]
      sliceNode = self.crosshairNode.GetCursorPositionXYZ(xyz)
      sliceLogic = None
      if sliceNode:
        appLogic = slicer.app.applicationLogic()
        if appLogic:
          sliceLogic = appLogic.GetSliceLogic(sliceNode)
      if sliceLogic:
        layerLogic =  sliceLogic.GetBackgroundLayer()
        xyToIJK = layerLogic.GetXYToIJKTransform()
        ijkFloat = xyToIJK.TransformDoublePoint(xyz)
        ijk = [_roundInt(value) for value in ijkFloat]
        self.updatePatchesTable(ijk)
        slicer.util.infoDisplay("Position: {}".format(ijk))

  #------------------------------------------------------------------------------
  def onInputDirChanged(self, dir_name):
    self.path_to_images = Path(str(dir_name))
    if not self.path_to_images.exists:
      logging.error('The directory {} does not exist'.format(self.path_to_images))
    else:  
      if len(self.image_list) > 0 and self.path_to_images:
        self.startProcessingFiles()

  #------------------------------------------------------------------------------
  def onLoadNonDicomData(self):
    slicer.util.openAddDataDialog()
  
  def openFileNamesDialog(self):
    file = qt.QFileDialog.getOpenFileName(None,"Choose the CSV Input", "","CSV files (*.csv)")
    if file:
      self.path_to_image_list = Path(file)
      self.ui.imageFileButton.setText(str(self.path_to_image_list))

      # read the excl sheet, and convert to dict
      try:
        with open(self.path_to_image_list, 'r') as f:
          dr = DictReader(f)
          if 'filename' not in dr.fieldnames:
            raise Exception("expecting the field-> filename")
          self.initData()
          self.image_list = [row['filename'] for row in dr]
      except Exception as e:
        slicer.util.errorDisplay("Error processing input csv\n ERROR:  {}".format(e))
        self.ui.imageFileButton.setText("Not Selected")
      slicer.util.infoDisplay( "Found a list of {} images".format(len(self.image_list)))
      if len(self.image_list) > 0 and self.path_to_images:
        self.startProcessingFiles()
    self.parent.show()

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
    elif layoutIndex == 7:
      self.layoutWidget.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)

  def onImageIndexChanged(self, scroll_pos):
    self.current_ind = scroll_pos-1
    self.updateNavigationUI()
    self.showImageAtCurrentInd()
    self.updatePatchesTable(clearTable=True)
    #TODO: Code for plotting the image at this index comes here

  def initData(self):
    self.image_list=[]
    self.current_ind = -1
    self.updateNavigationUI()

  def startProcessingFiles(self):
    if self.path_to_images and len(self.image_list) > 0:
      found_at_least_one = False
      for name in self.image_list:
        imgpath = self.path_to_images/(name +".jpg")
        if imgpath.exists():
          found_at_least_one = True
          break
      
      if found_at_least_one:
        self.current_ind = 0
        self.updateNavigationUI()
        self.showImageAtCurrentInd()
      else:
        slicer.util.errorDisplay("Couldn't find images from the list in directory: {}".format(self.path_to_image_list))

  def showImageAtCurrentInd(self):
    if len(self.image_list) == 0 or self.path_to_image_list is None:
      slicer.util.errorDisplay('Need to chose and image list and path to the images - make sure those are in')
      return
    if self.current_ind < 0 or self.current_ind >= len(self.image_list):
      slicer.util.warningDisplay("Wrong image index: {}".format(self.current_ind))
    
    imgpath = self.path_to_images / (self.image_list[self.current_ind] + '.jpg')
    try:
      if self.image_node is not None:
        utility.MRMLUtility.removeMRMLNode(self.image_node)
      #utility.MRMLUtility.loadMRMLNode('image_node', self.path_to_images, self.image_list[self.current_ind] + '.jpg', 'VolumeFile') 
      self.image_node = slicer.util.loadVolume(str(imgpath), {'singleFile':True})
    except Exception as e:
      slicer.util.errorDisplay("Couldn't load imagepath: {}\n ERROR: {}".format(imgpath, e))

#
# TTSegTool
#

class TTSegTool(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "TTSegTool"  # TODO: make this more human readable by adding spaces
    self.parent.categories = ["Slicelets"]  # TODO: set categories (folders where the module shows up in the module selector)
    self.parent.dependencies = []  # TODO: add here list of module names that this module requires
    self.parent.contributors = ["Hina Shah (UNC CH)"]  # TODO: replace with "Firstname Lastname (Organization)"
    # TODO: update with short description of the module and a link to online module documentation
    self.parent.helpText = """
Slicelet for Trichiasis segmentation and ground truth generation. For further details on this code
please look here: <a href="https://github.com/organization/projectname#TTSegTool">module documentation</a>.
"""
    # TODO: replace with organization, grant and thanks
    self.parent.acknowledgementText = """
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
"""
    iconsPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons', self.moduleName+'.png')
    parent.icon = qt.QIcon(iconsPath)

    # Additional initialization step after application startup is complete
    # TODO: remove slicer.app.connect("startupCompleted()", registerSampleData)

#
# TTSegToolWidget
#

class TTSegToolWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent=None):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.__init__(self, parent)
    VTKObservationMixin.__init__(self)  # needed for parameter node observation
    #
    # self._parameterNode = None
    # self._updatingGUIFromParameterNode = False

  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
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
    mainFrame.windowTitle = "TT Segmentation tool"
    mainFrame.setWindowFlags(qt.Qt.WindowCloseButtonHint | qt.Qt.WindowMaximizeButtonHint | qt.Qt.WindowTitleHint)
    iconPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons', self.moduleName+'.png')
    mainFrame.windowIcon = qt.QIcon(iconPath)
    mainFrame.connect('destroyed()', self.onSliceletClosed)
    print('Mainframe is none? : {}'.format(mainFrame is None))
    slicelet = TTSegToolSlicelet(mainFrame, self.developerMode, resourcePath=os.path.join(os.path.dirname(__file__), 'Resources/UI', self.moduleName+'.ui'))
    mainFrame.setSlicelet(slicelet)

    # Make the slicelet reachable from the Slicer python interactor for testing
    slicer.ttSegToolInstance = slicelet

    return slicelet

  def onSliceletClosed(self):
    logging.debug('Slicelet closed')

  #   except Exception as e:
  #     slicer.util.errorDisplay("Failed to compute results: "+str(e))
  #     import traceback
  #     traceback.print_exc()


# #
# # TTSegToolLogic
# #

# class TTSegToolLogic(ScriptedLoadableModuleLogic):
#   """This class should implement all the actual
#   computation done by your module.  The interface
#   should be such that other python code can import
#   this class and make use of the functionality without
#   requiring an instance of the Widget.
#   Uses ScriptedLoadableModuleLogic base class, available at:
#   https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
#   """

#   def __init__(self):
#     """
#     Called when the logic class is instantiated. Can be used for initializing member variables.
#     """
#     ScriptedLoadableModuleLogic.__init__(self)

#   def setDefaultParameters(self, parameterNode):
#     """
#     Initialize parameter node with default settings.
#     """
#     if not parameterNode.GetParameter("Threshold"):
#       parameterNode.SetParameter("Threshold", "100.0")
#     if not parameterNode.GetParameter("Invert"):
#       parameterNode.SetParameter("Invert", "false")

#   def process(self, inputVolume, outputVolume, imageThreshold, invert=False, showResult=True):
#     """
#     Run the processing algorithm.
#     Can be used without GUI widget.
#     :param inputVolume: volume to be thresholded
#     :param outputVolume: thresholding result
#     :param imageThreshold: values above/below this threshold will be set to 0
#     :param invert: if True then values above the threshold will be set to 0, otherwise values below are set to 0
#     :param showResult: show output volume in slice viewers
#     """

#     if not inputVolume or not outputVolume:
#       raise ValueError("Input or output volume is invalid")

#     import time
#     startTime = time.time()
#     logging.info('Processing started')

#     # Compute the thresholded output volume using the "Threshold Scalar Volume" CLI module
#     cliParams = {
#       'InputVolume': inputVolume.GetID(),
#       'OutputVolume': outputVolume.GetID(),
#       'ThresholdValue' : imageThreshold,
#       'ThresholdType' : 'Above' if invert else 'Below'
#       }
#     cliNode = slicer.cli.run(slicer.modules.thresholdscalarvolume, None, cliParams, wait_for_completion=True, update_display=showResult)
#     # We don't need the CLI module node anymore, remove it to not clutter the scene with it
#     slicer.mrmlScene.RemoveNode(cliNode)

#     stopTime = time.time()
#     logging.info('Processing completed in {0:.2f} seconds'.format(stopTime-startTime))

#
# TTSegToolTest
#

class TTSegToolTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear()

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_TTSegTool1()

  def test_TTSegTool1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    self.delayDisplay("Starting the test")

    # Get/create input data

    import SampleData
    registerSampleData()
    inputVolume = SampleData.downloadSample('TTSegTool1')
    self.delayDisplay('Loaded test data set')

    inputScalarRange = inputVolume.GetImageData().GetScalarRange()
    self.assertEqual(inputScalarRange[0], 0)
    self.assertEqual(inputScalarRange[1], 695)

    outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
    threshold = 100

    # Test the module logic

    logic = TTSegToolLogic()

    # Test algorithm with non-inverted threshold
    logic.process(inputVolume, outputVolume, threshold, True)
    outputScalarRange = outputVolume.GetImageData().GetScalarRange()
    self.assertEqual(outputScalarRange[0], inputScalarRange[0])
    self.assertEqual(outputScalarRange[1], threshold)

    # Test algorithm with inverted threshold
    logic.process(inputVolume, outputVolume, threshold, False)
    outputScalarRange = outputVolume.GetImageData().GetScalarRange()
    self.assertEqual(outputScalarRange[0], inputScalarRange[0])
    self.assertEqual(outputScalarRange[1], inputScalarRange[1])

    self.delayDisplay('Test passed')

def onSliceletClosed():
  logging.info('Closing the slicelet')

#
# Main
#
if __name__ == "__main__":
  #TODO: access and parse command line arguments
  #   Example: SlicerRt/src/BatchProcessing
  #   Ideally handle --xml

  import sys
  logging.debug( sys.argv )
  mainFrame = SliceletMainFrame()
  mainFrame.minimumWidth = 1200
  mainFrame.minimumHeight = 720
  mainFrame.windowTitle = "TT Segmentation tool"
  mainFrame.setWindowFlags(qt.Qt.WindowCloseButtonHint | qt.Qt.WindowMaximizeButtonHint | qt.Qt.WindowTitleHint)
  mainFrame.connect('destroyed()', onSliceletClosed)
  iconPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons/TTSegTool.png')
  mainFrame.windowIcon = qt.QIcon(iconPath)
  mainFrame = qt.QFrame()
  slicelet = TTSegToolSlicelet(mainFrame, resourcePath=os.path.join(os.path.dirname(__file__), 'Resources/UI/TTSegTool.ui'))
