import os
import qt
import unittest
import logging
from csv import DictReader, DictWriter
from pathlib import Path
import numpy as np

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
    self.saveCurrentImagePatchInfo()
    self.initData(clearScene=True)
    logging.info('Disconnecting something')

  #------------------------------------------------------------------------------
  def setDefaultParamaters(self):
    self.path_to_images = None
    self.path_to_segmentations = None
    self.path_to_image_list = None
    self.path_to_segmentations = None
    self.image_node = None
    self.segmentation_node = None
    self.segmentation_editor_node = None
    self.initData()
    
  #------------------------------------------------------------------------------
  def updateFiducialLabel(self, index):
    if len(self.image_list) == 0 or \
       self.path_to_images is None or \
        self.current_ind  not in range(len(self.image_list)):
      logging.warning('Cannot update patches table: Select a valid csv file and point to a correct folder with images')
      return
    
    row = self.ui.imagePatchesTableWidget.currentRow()
    new_label = self.ui.patchLabelComboBox.itemText(index)
    fid = slicer.modules.markups.logic().GetActiveListID()
    if len(fid) > 0:
      fidNode = slicer.util.getNode(fid)
      if row in range(fidNode.GetNumberOfFiducials()):
        fidNode.SetNthFiducialLabel(row, new_label)
        self.ui.imagePatchesTableWidget.item(row, 2).setText(new_label)

#------------------------------------------------------------------------------
  def addFiducial(self, row_id, ras, label=None):
    # This assumes that the row_id is already present in the patches table, 
    # Labels are taken from there when necessary
    if row_id is None or ras is None or row_id not in range(self.ui.imagePatchesTableWidget.rowCount):
      return

    # create fiducial
    fid = slicer.modules.markups.logic().GetActiveListID()
    if fid=='':
      slicer.modules.markups.logic().AddFiducial()
      fid = slicer.modules.markups.logic().GetActiveListID()
      fidNode = slicer.util.getNode(fid)
    else:
      fidNode = slicer.util.getNode(fid)
      fidNode.AddFiducial(0,0,0)

    fid_n = row_id
    if fid_n in range(fidNode.GetNumberOfFiducials()):
      if label is None:        
        label = self.ui.imagePatchesTableWidget.item(row_id, 2).text()
      fidNode.SetNthFiducialLabel(fid_n, label)
      fidNode.SetNthFiducialPosition(fid_n, ras[0], ras[1], ras[2])
      fidNode.SetNthFiducialSelected(fid_n, 0)

#------------------------------------------------------------------------------
  def addPatchRow(self, ijk, label=None):
    # Check the IJK and RAS is non-empty
    if ijk is None:
      return None
    
    row_id = self.ui.imagePatchesTableWidget.rowCount
    self.ui.imagePatchesTableWidget.insertRow(row_id)
    item = qt.QTableWidgetItem("{}".format(row_id+1))
    self.ui.imagePatchesTableWidget.setItem(row_id, 0, item)
    item1 = qt.QTableWidgetItem("{},{}".format(ijk[0], ijk[1]))
    self.ui.imagePatchesTableWidget.setItem(row_id, 1, item1)

    label_id = None
    if label is None:        
      label = self.ui.patchLabelComboBox.currentText
    else:
      all_labels = [self.ui.patchLabelComboBox.itemText(i) for i in range(self.ui.patchLabelComboBox.count)]
      if label not in all_labels:
        logging.warning('During adding row to patch table at row: {}, label: {} is marked unknown'.format(row_id, label))
        label = "Unknown"
      label_id = all_labels.index(label)
    
    item2 = qt.QTableWidgetItem("{}".format(label))
    self.ui.imagePatchesTableWidget.setItem(row_id, 2, item2)
    self.ui.imagePatchesTableWidget.selectRow(row_id)

    # Combo box is set after the row selection is done to get the correct 
    # current row while updating the fiducial labels. (callback on index change for combo box)
    if label_id is not None:
      self.ui.patchLabelComboBox.setCurrentIndex(label_id)
    
    return row_id

#------------------------------------------------------------------------------
  def updatePatchesTable(self, ijk=None, ras=None, clearTable = False):
    if len(self.image_list) == 0 or \
       self.path_to_images is None or \
        self.current_ind < 0 or self.current_ind >= len(self.image_list):
      logging.warning('Cannot update patches table: Select a valid csv file and point to a correct folder with images')
      return
    
    if clearTable:  
      self.ui.imagePatchesTableWidget.clearContents()
      self.ui.imagePatchesTableWidget.setRowCount(0)
      fid = slicer.modules.markups.logic().GetActiveListID()
      if len(fid) > 0:
        fidNode = slicer.util.getNode(fid)
        fidNode.RemoveAllControlPoints()
      return
    
    row_id = None
    if ijk is not None:
      row_id = self.addPatchRow(ijk)
      # item3 = qt.QComboBox(self.ui.imagePatchesTableWidget)
      # item3.addItems(["TT", "Healthy", "Epilation", "Unknown"])
      # self.ui.imagePatchesTableWidget.setCellWidget(row_id, 2, item3)
    
    # Create the fiducial
    if ras is not None and row_id is not None :
      self.addFiducial(row_id, ras)
      self.updateFiducialSelection(row_id, 2, row_id, 2)

  #------------------------------------------------------------------------------
  def updateNavigationUI(self):
    if self.ui == None:
      return
    ind = None
    detailsText=None
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
    self.ui.segmenationDirButton.connect('directoryChanged(QString)', self.onSegmentationDirChanged)
    self.ui.imageFileButton.clicked.connect(self.openFileNamesDialog)
    self.ui.imageNavigationScrollBar.setTracking(False)
    self.ui.imageNavigationScrollBar.valueChanged.connect(self.onImageIndexChanged)
    self.ui.keepPatchPushButton.clicked.connect(self.onSavePatchesButtonClicked)
    self.ui.delPatchPushButton.clicked.connect(self.onDelPatchClicked)
    self.ui.patchLabelComboBox.addItems(["TT", "Healthy", "Epilation", "Unknown"])
    self.ui.patchLabelComboBox.currentIndexChanged.connect(self.updateFiducialLabel)
    self.ui.imagePatchesTableWidget.currentCellChanged.connect(self.updateFiducialSelection)
    self.ui.showSegmentationCheckBox.stateChanged.connect(self.changeSegmentationVisibility)

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

  def changeSegmentationVisibility(self, state):
    if self.segmentation_node is None:
      return
    dn = self.segmentation_node.GetDisplayNode()
    dn.SetVisibility(state)
    if self.ui is not None:
      self.ui.SegmentEditorWidget.setEnabled(state)

  #------------------------------------------------------------------------------
  def onSavePatchesButtonClicked(self):
    self.saveCurrentImagePatchInfo()

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------
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

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------
  def onDelPatchClicked(self):
    if len(self.image_list) == 0 or \
       self.path_to_images is None or \
        self.current_ind < 0 or self.current_ind >= len(self.image_list):
      logging.warning('Cannot update patches table: Select a valid csv file and point to a correct folder with images')
      return
    
    row = self.ui.imagePatchesTableWidget.currentRow()
    logging.info('Removing image patch at position: {}'.format(row))
    self.ui.imagePatchesTableWidget.removeRow(row)

    fid = slicer.modules.markups.logic().GetActiveListID()
    if len(fid) > 0:
      fidNode = slicer.util.getNode(fid)
      if row in range(fidNode.GetNumberOfFiducials()):
        fidNode.RemoveNthControlPoint(row)
    if self.ui.imagePatchesTableWidget.rowCount > 0:
      self.ui.imagePatchesTableWidget.selectRow( self.ui.imagePatchesTableWidget.rowCount - 1)

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------
  def OnClick(self, caller, event):
    print('Inside the onclick')
    if len(self.image_list) == 0 or \
       self.path_to_images is None or \
        self.current_ind not in range(len(self.image_list)):
      logging.warning('Nothing to do OnClick: Select a valid csv file and point to a correct folder with images')
      return

    if self.interactor is not None and self.crosshairNode is not None:
      def _roundInt(value):
        try:
          return int(round(value))
        except ValueError:
          logging.info('Getting a ValueError during roundupt')
          return 0

      xyz = [0,0,0]
      ras = [0,0,0]
      sliceNode = self.crosshairNode.GetCursorPositionXYZ(xyz)
      print('Got XYZ {}, slicenode: {}'.format(xyz, sliceNode))
      self.crosshairNode.GetCursorPositionRAS(ras)
      if sliceNode is not None and sliceNode.GetName() == 'Red':
        lm = self.layoutWidget.layoutManager()
        sliceLogic = lm.sliceWidget('Red').sliceLogic()
        if sliceLogic is None:
          print('Empyt slice logic')
        else:
          layerLogic =  sliceLogic.GetBackgroundLayer()
          xyToIJK = layerLogic.GetXYToIJKTransform()
          ijkFloat = xyToIJK.TransformDoublePoint(xyz)
          ijk = [_roundInt(value) for value in ijkFloat]
          print('IJK: {}'.format(ijk))
          self.updatePatchesTable(ijk=ijk, ras=ras)
      else:
        print('Something wrong with sliceNode: {}'.format(sliceNode))

      # if sliceNode:
      #   appLogic = slicer.app.applicationLogic()
      #   print('Applogic: {}'.format(appLogic))
      #   if appLogic:
      #     sliceLogic = appLogic.GetSliceLogic(sliceNode)
      #     print('Slicelogic: {}'.format(sliceLogic))
      #     if sliceLogic:
      #       layerLogic =  sliceLogic.GetBackgroundLayer()
      #       xyToIJK = layerLogic.GetXYToIJKTransform()
      #       ijkFloat = xyToIJK.TransformDoublePoint(xyz)
      #       ijk = [_roundInt(value) for value in ijkFloat]
      #       print('IJK: {}'.format(ijk))
      #       self.updatePatchesTable(ijk=ijk, ras=ras)
      #   # slicer.util.infoDisplay("Position: {}".format(ijk))

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------
  def onInputDirChanged(self, dir_name):
    self.path_to_images = Path(str(dir_name))
    if not self.path_to_images.exists:
      logging.error('The directory {} does not exist'.format(self.path_to_images))
    else:  
      if len(self.image_list) > 0 and self.path_to_images:
        self.startProcessingFiles()

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------
  def onSegmentationDirChanged(self, dir_name):
    self.path_to_segmentations = Path(str(dir_name))
    if not self.path_to_segmentations:
      logging.error('The directory {} does not exist'.format(self.path_to_images))
    else:  
      if len(self.image_list) > 0 and self.path_to_images:
        self.startLoadingSegmentations()

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------
  def onLoadNonDicomData(self):
    slicer.util.openAddDataDialog()
  
  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------
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
        slicer.util.errorDisplay("Error processing input csv \n ERROR:  {}".format(e))
        self.ui.imageFileButton.setText("Not Selected")
      slicer.util.infoDisplay( "Found a list of {} images".format(len(self.image_list)))
      if len(self.image_list) > 0 and self.path_to_images:
        self.startProcessingFiles()
    self.parent.show()
#------------------------------------------------------------------------------
#------------------------------------------------------------------------------
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

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------  
  def onImageIndexChanged(self, scroll_pos):
    self.saveCurrentImagePatchInfo()
    self.current_ind = scroll_pos-1
    self.updateNavigationUI()
    if self.current_ind >=0 and len(self.image_list) > 0:
      self.showImageAtCurrentInd()
      if self.path_to_segmentations is not None:
        self.loadCurrentSegmentation()
    self.updatePatchesTable(clearTable=True)
    self.loadExistingPatches()

#------------------------------------------------------------------------------
#------------------------------------------------------------------------------  
  def initData(self, clearScene = False):
    self.image_list=[]
    self.current_ind = -1

    if self.ui is not None and self.ui.imagePatchesTableWidget is not None:
      for row in range(self.ui.imagePatchesTableWidget.rowCount):
            self.ui.imagePatchesTableWidget.removeRow(row)
    fid = slicer.modules.markups.logic().GetActiveListID()
    if len(fid) > 0:
      fidNode = slicer.util.getNode(fid)
      for row in range(fidNode.GetNumberOfFiducials()):
        fidNode.RemoveNthControlPoint(0)
    if self.image_node is not None:
      utility.MRMLUtility.removeMRMLNode(self.image_node)
    if self.segmentation_node is not None:
      utility.MRMLUtility.removeMRMLNode(self.segmentation_node)
      utility.MRMLUtility.removeMRMLNode(self.segmentation_editor_node)
    self.updateNavigationUI()

#------------------------------------------------------------------------------
#------------------------------------------------------------------------------  
  def getCurrentPatchFileName(self):
    if self.image_list is not None and len(self.image_list) > 0 and self.current_ind in range( len(self.image_list)):
      image_name = self.image_list[self.current_ind]
      csv_file_name = image_name + '_patches.csv'
      return csv_file_name
    else:
      return None

#------------------------------------------------------------------------------
#------------------------------------------------------------------------------  
  def getCurrentSegmentationFileName(self, ind=None):
    if self.image_list is not None and len(self.image_list) > 0 and (self.current_ind in range( len(self.image_list)) or ind is not None):
      if ind is None:
        ind = self.current_ind
      image_name = self.image_list[ind]
      segmentation_file_name = image_name + '.nrrd'
      return segmentation_file_name
    else:
      return None

#------------------------------------------------------------------------------
#------------------------------------------------------------------------------  
  def startProcessingFiles(self):
    if self.path_to_images and len(self.image_list) > 0:
      found_at_least_one = False
      for name in self.image_list:
        imgpath = self.path_to_images/ (name+'.jpg')
        if imgpath.exists():
          found_at_least_one = True
          break
      
      if found_at_least_one:
        self.current_ind = 0
        self.updateNavigationUI()
        self.showImageAtCurrentInd()
      else:
        slicer.util.errorDisplay("Couldn't find images from the list in directory: {}".format(self.path_to_image_list))

  def startLoadingSegmentations(self):
    if self.path_to_segmentations and len(self.image_list) > 0:
      found_at_least_one = False
      for ind in range(len(self.image_list)):
        imgpath = self.path_to_segmentations / self.getCurrentSegmentationFileName(ind=ind)
        if imgpath.exists():
          found_at_least_one = True
          break
      
      if found_at_least_one:
        if self.ui is not None:
          self.changeSegmentationVisibility(self.ui.showSegmentationCheckBox.isChecked())

        if self.current_ind >= 0:
          self.loadCurrentSegmentation()
        else:
          if self.path_to_images and len(self.image_list) > 0:
            self.current_ind = 0
            self.updateNavigationUI()
            self.showImageAtCurrentInd()
            self.loadCurrentSegmentation()
      else:
        slicer.util.errorDisplay("Couldn't find images from the list in directory: {}".format(self.path_to_image_list))

  def loadCurrentSegmentation(self):
    if len(self.image_list) == 0 or self.path_to_image_list is None: 
      slicer.util.errorDisplay('Show image at current IND: Need to chose an image list and path to the images - make sure those are in')
      return
    if self.current_ind < 0 or self.current_ind >= len(self.image_list):
      slicer.util.warningDisplay("Wrong image index: {}".format(self.current_ind))
    
    imgpath = self.path_to_segmentations /  self.getCurrentSegmentationFileName()
    try:
      if self.segmentation_node is not None:
        utility.MRMLUtility.removeMRMLNode(self.segmentation_node)
        utility.MRMLUtility.removeMRMLNode(self.segmentation_editor_node)
      #utility.MRMLUtility.loadMRMLNode('image_node', self.path_to_images, self.image_list[self.current_ind] + '.jpg', 'VolumeFile') 
      self.segmentation_node = slicer.util.loadSegmentation(str(imgpath))
      dn = self.segmentation_node.GetDisplayNode()
      dn.SetVisibility2DOutline(0)
      dn.SetVisibility2DFill(1)
      if self.ui is not None:
        self.ui.SegmentEditorWidget.setMRMLScene(slicer.mrmlScene)
        self.segmentation_editor_node = slicer.vtkMRMLSegmentEditorNode()
        slicer.mrmlScene.AddNode(self.segmentation_editor_node)
        self.ui.SegmentEditorWidget.setMRMLSegmentEditorNode(self.segmentation_editor_node)
        self.ui.SegmentEditorWidget.setSegmentationNode(self.segmentation_node)
        if self.image_node is not None:
          self.ui.SegmentEditorWidget.setMasterVolumeNode(self.image_node)
        visibility = self.ui.showSegmentationCheckBox.isChecked()
        dn.SetVisibility(visibility)

    except Exception as e:
      slicer.util.errorDisplay("Couldn't load imagepath: {}\n ERROR: {}".format(imgpath, e))

#------------------------------------------------------------------------------
#------------------------------------------------------------------------------  
  def showImageAtCurrentInd(self):
    if len(self.image_list) == 0 or self.path_to_image_list is None:
      slicer.util.errorDisplay('Show image at current IND: Need to chose an image list and path to the images - make sure those are in')
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

#------------------------------------------------------------------------------
#------------------------------------------------------------------------------  
  def loadExistingPatches(self):
    if len(self.image_list) == 0 or \
       self.path_to_images is None or \
        self.current_ind < 0 or self.current_ind >= len(self.image_list):
      logging.warning('Cannot load existincg patch info: Select a valid csv file and point to a correct folder with images')
      return

    if self.ui.imagePatchesTableWidget is None:
      logging.warning('Image Patches table is None, returning from saveCurrentImagePatchInfo')
      return

    csv_file_name = self.getCurrentPatchFileName()
    if csv_file_name is None:
      logging.warining('Error getting the name of the patches file, returning')
      return

    csv_file_path = self.path_to_images / csv_file_name
    if csv_file_path.exists():
      logging.info('Attempting to read existing patches file')
      try:
        with open(csv_file_path, 'r') as fh:
          reader = DictReader(fh)
          for row in reader:
            ijk = None
            ijk = [int(row['x']), int(row['y']), 0]
            # Adding row to the table will also update the combo box
            row_id = self.addPatchRow(ijk, label=row['label'])
            logging.debug('Added row: {}, ijk: {}, label: {}'.format(row_id, ijk, row['label']))
            logging.debug('Combobox label: {}, table label: {}'.format(self.ui.patchLabelComboBox.currentText,  self.ui.imagePatchesTableWidget.item(row_id, 2).text()))
            if row_id is not None:
              # Get physical coordinates from voxel coordinates
              volumeIjkToRas = vtk.vtkMatrix4x4()
              self.image_node.GetIJKToRASMatrix(volumeIjkToRas)
              point_VolumeRas = [0, 0, 0, 1]
              volumeIjkToRas.MultiplyPoint(np.append(ijk,1.0), point_VolumeRas)
              # If volume node is transformed, apply that transform to get volume's RAS coordinates
              transformVolumeRasToRas = vtk.vtkGeneralTransform()
              slicer.vtkMRMLTransformNode.GetTransformBetweenNodes(self.image_node.GetParentTransformNode(), None, transformVolumeRasToRas)
              point_Ras = transformVolumeRasToRas.TransformPoint(point_VolumeRas[0:3])
              self.addFiducial(row_id=row_id, ras=point_Ras)
              logging.debug('After adding fiducial: ')
              logging.debug('Combobox label: {}, table label: {}'.format(self.ui.patchLabelComboBox.currentText,  self.ui.imagePatchesTableWidget.item(row_id, 2).text()))
              self.updateFiducialSelection(row_id, 2, row_id, 2)

      except IOError as e:
        logging.warning("Couldn't read the patches file {}, clearing the widget table: \n {}".format(csv_file_path, e))
        self.updatePatchesTable(clearTable=True)
      except Exception as e:
        logging.warning("Error loading existing path file {}, error: \n {} ".format(csv_file_path, e))
        self.updatePatchesTable(clearTable=True)

#------------------------------------------------------------------------------
#------------------------------------------------------------------------------  
  def saveCurrentImagePatchInfo(self):
    if len(self.image_list) == 0 or \
       self.path_to_images is None or \
        self.current_ind < 0 or self.current_ind >= len(self.image_list):
      logging.warning('Cannot save current patch info: Select a valid csv file and point to a correct folder with images')
      return

    if self.ui.imagePatchesTableWidget is None:
      logging.warning('Image Patches table is None, returning from saveCurrentImagePatchInfo')
      return

    csv_file_rows = []
    numrows = self.ui.imagePatchesTableWidget.rowCount
    try:
      for row in range(numrows):
        csv_row = {}
        text = self.ui.imagePatchesTableWidget.item(row, 1).text()
        csv_row['x'] = text.split(',')[0]
        csv_row['y'] = text.split(',')[1]
        csv_row['label'] = self.ui.imagePatchesTableWidget.item(row, 2).text()
        csv_file_rows.append(csv_row)
    except Exception as e:
      logging.error('Error parsing the table widget: \n {}'.format(e))
      return
    
    if len(csv_file_rows) == 0:
      logging.info('No rows were parsed from the Patches Table, nothing to save: returning')
      return

    csv_file_name = self.getCurrentPatchFileName()
    if csv_file_name is None:
      logging.warining('Error getting the name of the patches file, returning')
      return

    csv_file_path = self.path_to_images / csv_file_name
    try:
      with open(csv_file_path, 'w') as fh:
        writer = DictWriter(fh, csv_file_rows[0].keys())
        writer.writeheader()
        writer.writerows(csv_file_rows)
      logging.info('Wrote the patches file: {}'.format(csv_file_path))
    except IOError as e:
      logging.error('Error writing the csv file: {} \n  {}'.format(csv_file_path, e))

  def updateFiducialSelection(self, row, col, prevrow, prevcol):
    logging.debug('In updatefiducial selection')
    if row not in range(self.ui.imagePatchesTableWidget.rowCount):
      return

    comboBoxLabel = self.ui.patchLabelComboBox.currentText
    tableLabel = self.ui.imagePatchesTableWidget.item(row, 2).text()
    logging.debug('Combobox label: {}, tablelabel: {}'.format(comboBoxLabel, tableLabel))
    if tableLabel != comboBoxLabel:
      all_labels = [self.ui.patchLabelComboBox.itemText(i) for i in range(self.ui.patchLabelComboBox.count)]
      if tableLabel not in all_labels:
        logging.warning('During adding row to patch table at row: {}, label: {} is marked unknown'.format(row, tableLabel))
        tableLabel = "Unknown"
      label_id = all_labels.index(tableLabel)
      self.ui.patchLabelComboBox.setCurrentIndex(label_id)

    fid = slicer.modules.markups.logic().GetActiveListID()
    if len(fid) > 0:
      fidNode = slicer.util.getNode(fid)
      fiducialCount = fidNode.GetNumberOfFiducials()
      logging.debug('Fiducial count is: {}'.format(fiducialCount))
      if row in range(fiducialCount):
        for r in range(fiducialCount):
          if r == row:
            fidNode.SetNthFiducialSelected(r, 1)
          else:
            fidNode.SetNthFiducialSelected(r, 0)

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
    slicelet = TTSegToolSlicelet(mainFrame, self.developerMode, resourcePath=os.path.join(os.path.dirname(__file__), 'Resources/UI', self.moduleName+'.ui'))
    mainFrame.setSlicelet(slicelet)

    # Make the slicelet reachable from the Slicer python interactor for testing
    slicer.ttSegToolInstance = slicelet

    return slicelet

  def onSliceletClosed(self):
    logging.debug('Slicelet closed')

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
  mainFrame.minimumHeight = 1080
  mainFrame.windowTitle = "TT Segmentation tool"
  mainFrame.setWindowFlags(qt.Qt.WindowCloseButtonHint | qt.Qt.WindowMaximizeButtonHint | qt.Qt.WindowTitleHint)
  mainFrame.connect('destroyed()', onSliceletClosed)
  iconPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons/TTSegTool.png')
  mainFrame.windowIcon = qt.QIcon(iconPath)
  # mainFrame = qt.QFrame()
  slicelet = TTSegToolSlicelet(mainFrame, resourcePath=os.path.join(os.path.dirname(__file__), 'Resources/UI/TTSegTool.ui'))
