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

#   #
#   # TTSegToolSliceletWidget
#   #
# class TTSegToolSliceletWidget:
#     def __init__(self, parent=None):
#       try:
#         parent
#         self.parent = parent

#       except Exception as e:
#         import traceback
#         traceback.print_exc(
#         logging.error("There is no parent to TTSegToolSliceletWidget!"))

class SliceletMainFrame(qt.QDialog):
    def __init__(self):
      qt.QDialog.__init__(self)
      self.slicelet = None

    def setSlicelet(self, slicelet):
      self.slicelet = slicelet

    def hideEvent(self, event):
      self.slicelet.disconnect()
      self.slicelet = None

class TTSegToolSlicelet(VTKObservationMixin):
    def __init__(self, parent, developerMode=False, resourcePath=None):
      VTKObservationMixin.__init__(self)
      slicer.mrmlScene.Clear()
      self.logic = None
      self.parent = parent
      self.parent.showMaximized()
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
        w = self.parent.width
        uiWidget.minimumWidth = int(w*0.4)
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        self.setupConnections()

      self.layoutWidget = slicer.qMRMLLayoutWidget() 
      self.layoutWidget.setMRMLScene(slicer.mrmlScene)
      self.parent.layout().addWidget(self.layoutWidget,2)
      self.onViewSelect(7)
      
      # setup self connections
      self.crosshairNode=slicer.util.getNode('Crosshair')
      # self.setupLayoutConnections()
      self.parent.show()

    #------------------------------------------------------------------------------
    def disconnect(self):
      self.updateMasterDictAndTable()
      self.saveCurrentImagePatchInfo()
      self.saveCurrentRowToMaster()
      self.writeFinalMasterCSV()
      self.initData()
      self.updateUI()
      logging.info('Disconnecting something')

  #### CONNECTIONS #####
    #------------------------------------------------------------------------------
    def setupConnections(self):
      self.ui.imageDirButton.connect('directoryChanged(QString)', self.onInputDirChanged)
      self.ui.imageFileButton.clicked.connect(self.openFileNamesDialog)
      self.ui.loadCSVPushButton.clicked.connect(self.loadData)
      # Image navigation and master csv updates
      self.ui.saveMasterFileButton.clicked.connect(self.writeFinalMasterCSV)
      self.ui.imageNavigationScrollBar.setTracking(False)
      self.ui.imageNavigationScrollBar.valueChanged.connect(self.onImageIndexChanged)
      self.ui.findUngradedButton.clicked.connect(self.onFindUngradedClicked)
      self.ui.imageDetailsTable.itemClicked.connect(self.onImageDetailsRowClicked)
      # Patch management
      self.ui.keepPatchPushButton.clicked.connect(self.onSavePatchesButtonClicked)
      self.ui.delPatchPushButton.clicked.connect(self.onDelPatchClicked)
      self.ui.patchLabelComboBox.addItems(["TT", "Probable TT", "Healthy", "Epilation", "Probable Epilation", 
      "Unknown"])
      self.ui.patchLabelComboBox.currentIndexChanged.connect(self.updateFiducialLabel)
      self.ui.imagePatchesTableWidget.currentCellChanged.connect(self.updateFiducialSelection)
      # segmentation management
      self.ui.showSegmentationCheckBox.stateChanged.connect(self.changeSegmentationVisibility)

    #------------------------------------------------------------------------------
    def setupLayoutConnections(self, add=True):
      if self.layoutWidget is None:
        logging.warning('Layout widget is not set')
      
      lm = self.layoutWidget.layoutManager()
      sw = lm.sliceWidget('Red')
      self.interactor = sw.interactorStyle().GetInteractor()
      if add:
        self.interactor.AddObserver(vtk.vtkCommand.LeftButtonPressEvent, self.OnClick)

  ##### Data cleanup/initialization ############
    #------------------------------------------------------------------------------
    def setDefaultParamaters(self):
      self.path_to_server = None
      self.path_to_image_details = None
      self.image_node = None # holds the current image
      self.segmentation_node = None # holds the current segmentation
      self.segmentation_editor_node = None # holds the current segment editor node
      self.interactor = None
      self.crosshairNode = None
      self.user_name = None
      self.tmp_csv_file_name = None
      self.initData()
      self.updateUI()

  #------------------------------------------------------------------------------  
    def initData(self):
      self.image_list=[]
      self.current_ind = -1

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
      # self.updateNavigationUI()

  ##### UI Updates ###########
  #------------------------------------------------------------------------------
    def updateUI(self):
      self.current_ind = -1
      if self.current_ind < 0:
        if self.ui is not None and self.ui.imagePatchesTableWidget is not None:
            for row in range(self.ui.imagePatchesTableWidget.rowCount):
                self.ui.imagePatchesTableWidget.removeRow(row)
      self.updateNavigationUI()

  #------------------------------------------------------------------------------
    def updateNavigationUI(self):
      logging.debug('In updatenavui')
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
        detailsText = "::: Image {}/{} ::: ID ::: {} ::: Eye ::: {}".format(ind, max, self.image_list[self.current_ind]['cid'], self.image_list[self.current_ind]['eye'])
      else:
        detailsText = "Image list empty"
      
      self.ui.imagePosLabel.setText("{}/{}".format(ind,max))
      self.ui.imageNavigationScrollBar.setMinimum(min)
      self.ui.imageNavigationScrollBar.setMaximum(max)
      self.ui.imageDetailsLabel.setText(detailsText)
      self.ui.imageDetailsTable.setEnabled(self.current_ind >= 0)
      if self.current_ind >= 0:
        self.ui.imageDetailsTable.selectRow(self.current_ind)


  ############ Fiducial hanling ###############
    #------------------------------------------------------------------------------
    def updateFiducialLabel(self, index):
      if len(self.image_list) == 0 or \
        self.path_to_server is None or \
          self.current_ind  not in range(len(self.image_list)):
        logging.info('Cannot update Fiducial label: Select a valid image info file.')
        return

      row = self.ui.imagePatchesTableWidget.currentRow()
      new_label = self.ui.patchLabelComboBox.itemText(index)
      fid = slicer.modules.markups.logic().GetActiveListID()
      if len(fid) > 0:
        fidNode = slicer.util.getNode(fid)
        if row in range(fidNode.GetNumberOfFiducials()):
          fidNode.SetNthFiducialLabel(row, new_label)
          self.ui.imagePatchesTableWidget.item(row, 1).setText(new_label)

  #------------------------------------------------------------------------------
    def addFiducial(self, row_id, ras, label=None):
      if len(self.image_list) == 0 or \
        self.path_to_server is None or \
          self.current_ind  not in range(len(self.image_list)):
        logging.info('Cannot add Fiducial label:  No images or select a valid image info file.')
        return

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
          label = self.ui.imagePatchesTableWidget.item(row_id, 1).text()
        fidNode.SetNthFiducialLabel(fid_n, label)
        fidNode.SetNthFiducialPosition(fid_n, ras[0], ras[1], ras[2])
        fidNode.SetNthFiducialSelected(fid_n, 0)

  ##### Patch table management #####
  #------------------------------------------------------------------------------
    def addPatchRow(self, ijk, label=None):
      # Check the IJK and RAS is non-empty
      if ijk is None:
        return None
      # Make sure the coordinates are inside the frame
      if self.image_node is None:
        return
      
      imageData = self.image_node.GetImageData()
      if not imageData:
        return
      dims =  imageData.GetDimensions()
      for dim in range(len(ijk)):
        if ijk[dim] < 0 or ijk[dim] >= dims[dim]:
          logging.debug('Clicked out of frame, returning')
          return

      row_id = self.ui.imagePatchesTableWidget.rowCount
      self.ui.imagePatchesTableWidget.insertRow(row_id)
      item1 = qt.QTableWidgetItem("{},{}".format(ijk[0], ijk[1]))
      self.ui.imagePatchesTableWidget.setItem(row_id, 0, item1)

      label_id = None
      if label is None:
        label = self.ui.patchLabelComboBox.currentText
      else:
        all_labels = [self.ui.patchLabelComboBox.itemText(i) for i in range(self.ui.patchLabelComboBox.count)]
        if label not in all_labels:
          logging.info('During adding row to patch table at row: {}, label: {} is marked unknown'.format(row_id, label))
          label = "Unknown"
        label_id = all_labels.index(label)

      item2 = qt.QTableWidgetItem("{}".format(label))
      self.ui.imagePatchesTableWidget.setItem(row_id, 1, item2)
      self.ui.imagePatchesTableWidget.selectRow(row_id)

      # Combo box is set after the row selection is done to get the correct 
      # current row while updating the fiducial labels. (callback on index change for combo box)
      if label_id is not None:
        self.ui.patchLabelComboBox.setCurrentIndex(label_id)

      return row_id

  #------------------------------------------------------------------------------
    def updatePatchesTable(self, ijk=None, ras=None, clearTable = False):
      if len(self.image_list) == 0 or \
        self.path_to_server is None or \
          self.current_ind < 0 or self.current_ind >= len(self.image_list):
        logging.info('Cannot update patches table: No images or select a valid image info file.')
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
      # Create the fiducial
      if ras is not None and row_id is not None :
        self.addFiducial(row_id, ras)
        self.updateFiducialSelection(row_id)

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
    def onDelPatchClicked(self):
      if len(self.image_list) == 0 or \
        self.path_to_server is None or \
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
      print('Before updating master: {}'.format(self.ui.imagePatchesTableWidget.rowCount))
      self.updateMasterDictAndTable()

    #------------------------------------------------------------------------------
    #------------------------------------------------------------------------------
    def OnClick(self, caller, event):
      logging.debug('Inside the onclick')
      if len(self.image_list) == 0 or \
        self.path_to_server is None or \
          self.current_ind not in range(len(self.image_list)):
        logging.info('Nothing to do OnClick: Load the data first')
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
        self.crosshairNode.GetCursorPositionRAS(ras)
        if sliceNode is not None and sliceNode.GetName() == 'Red':
          lm = self.layoutWidget.layoutManager()
          sliceLogic = lm.sliceWidget('Red').sliceLogic()
          if sliceLogic is None:
            logging.debug('Empyt slice logic')
          else:
            layerLogic =  sliceLogic.GetBackgroundLayer()
            xyToIJK = layerLogic.GetXYToIJKTransform()
            ijkFloat = xyToIJK.TransformDoublePoint(xyz)
            ijk = [_roundInt(value) for value in ijkFloat]
            self.updatePatchesTable(ijk=ijk, ras=ras)
            self.updateMasterDictAndTable()
        else:
          logging.debug('Something wrong with sliceNode: {}'.format(sliceNode))

    #------------------------------------------------------------------------------
    #------------------------------------------------------------------------------
    def onInputDirChanged(self, dir_name):
      self.path_to_server = Path(str(dir_name))
      if not self.path_to_server.exists():
        logging.error('The directory {} does not exist'.format(self.path_to_server))

    #------------------------------------------------------------------------------
    #------------------------------------------------------------------------------
    def openFileNamesDialog(self):
      file = qt.QFileDialog.getOpenFileName(None,"Choose the CSV Input", "","CSV files (*.csv)")
      if file:
        self.path_to_image_details = Path(file)
        self.ui.imageFileButton.setText(str(self.path_to_image_details))
        if self.path_to_server is not None:
          return

        # Try to estimate the server path:
        if 'EGower' in self.path_to_image_details.parts:
          ind = self.path_to_image_details.parts.index('EGower')
          ancestor = Path()
          for i in range(ind+1):
            ancestor = ancestor/ self.path_to_image_details.parts[i]
        else:
          ancestor = self.path_to_image_details.parts[0]
        self.ui.imageDirButton.directory = str(ancestor)

  ######## MASTER DATA FILE Manipulation ####################
  #---------------------------------------------------------
    def loadData(self):
      # read the excl sheet, and convert to dict
      if len(self.ui.usernameLineEdit.text) == 0:
        slicer.util.errorDisplay("Pleae provide a username", parent=self.parent)
        return
      if self.path_to_image_details is None:
        slicer.util.errorDisplay('Please provide a valid Master CSV File', parent=self.parent)
        return
      if self.path_to_server is None:
        slicer.util.errorDisplay('Please provide a valid server path ', parent=self.parent)
        return
      if not self.checkMasterFileForRequiredFields():
        slicer.util.errorDisplay('Did not find the fields that are at least required', parent=self.parent)

      logging.info('Found the required fields in the master file! Loading')
      try:
        self.user_name = self.ui.usernameLineEdit.text
        self.initData()
        self.updateUI()
        image_list = None
        image_list = self.readCSV(self.path_to_image_details)
        if len(image_list) == 0:
          raise IOError('Error reading the Master CSV File')
        self.createMasterDict(image_list)
      except Exception as e:
        slicer.util.errorDisplay("Error processing input csv \n ERROR:  {}".format(e), parent=self.parent)
        self.ui.imageFileButton.setText("Not Selected")
      slicer.util.infoDisplay("Found a list of {} images".format(len(self.image_list)), parent=self.parent)
      if len(self.image_list) > 0:
        self.startProcessingFiles()
        self.ui.inputsCollapsibleButton.collapsed = True
        self.fillMasterTable()
      self.parent.show()

  #---------------------------------------------------------
    def checkMasterFileForRequiredFields(self):
      all_good = True
      with open(self.path_to_image_details, 'r', newline='') as f:
          dr = DictReader(f)
          all_good = all_good & ('cid' in dr.fieldnames) \
                              & ('eye' in dr.fieldnames) \
                              & ('tt present' in dr.fieldnames) \
                                & ('tt sev' in dr.fieldnames) \
                                  & ('n lashes touching' in dr.fieldnames) \
                                    & ('epilation sev' in dr.fieldnames) \
                                      & ('image path' in dr.fieldnames) \
                                        & ('segmentation path' in dr.fieldnames) \
                                          & ('patches path' in dr.fieldnames)
      return all_good

  #------------------------------------------------------------------------------
    def addOptionalKey(self, row, key):
      if key not in row:
        row[key] = 0
      else:
        row[key] = int(row[key])

  #------------------------------------------------------------------------------
    def createMasterDict(self, image_list):
      # Make sure that image path and segmentation path are not empty
      # update the paths to be absolute
      # create a temp version of the output master file (time stamped)
      new_output_dir = self.path_to_image_details.parent / ('Patches_' + self.user_name)
      if not new_output_dir.is_dir():
          new_output_dir.mkdir(parents=True)
      progress = qt.QProgressDialog("Loading Master CSV", "Abort Load", 0, len(image_list), self.parent)
      # progress.setWindowModality(qt.Qt.WindowModal)

      for row_id, row in enumerate(image_list):
        progress.setValue(row_id)
        if progress.wasCanceled:
          break

        if len(row['image path']) ==0 or len(row['segmentation path']) == 0:
          logging.error('Found an empty Image path or Segmentation path in the master file')
          self.image_list = []
          break
        row['image path'] = self.path_to_server / row['image path']
        row['segmentation path'] = self.path_to_server / row['segmentation path']
        create_new = False
        try_to_read_patches = False
        if len(row['patches path']) > 0:
          row['patches path'] = self.path_to_server / row['patches path']
          if row['patches path'].exists():
            try_to_read_patches = False
          else:
            create_new = True
        else:
          create_new = True

        if create_new:
          image_name = (row['image path'].name).split('.')[0]
          row['patches path'] = new_output_dir / (image_name + '.csv')
          try_to_read_patches = True
        try:
          row['tt present'] = int(row['tt present'])
          row['tt sev'] = int(row['tt sev'])
          row['n lashes touching'] = int(row['n lashes touching'])
          row['epilation sev'] = int(row['epilation sev'])
        
          # Add any missing keys and initialize a temp file.
          self.addOptionalKey(row, 'graded')
          self.addOptionalKey(row, 'blurry')
          self.addOptionalKey(row, 'mislabeled')
          self.addOptionalKey(row, 'n samples')
          self.addOptionalKey(row, 'n tt')
          self.addOptionalKey(row, 'n probtt')
          self.addOptionalKey(row, 'n epi')
          self.addOptionalKey(row, 'n probepi')
          self.addOptionalKey(row, 'n healthy')
          self.addOptionalKey(row, 'n none')
        except Exception as e:
          logging.error('Error either converting keys to in or adding other keys')
          self.image_list = []
          break
        if try_to_read_patches and row['patches path'].exists():
          patch_rows = self.readCSV(row['patches path'])
          if len(patch_rows) == 0:
            logging.warning("Error reading pre-existing patches file: {}".format(row['patches path']))
          row['n samples'] = len(patch_rows)
          # ["TT", "Probable TT", "Healthy", "Epilation", "Unknown"]
          row['n tt'] = len( [l for l in patch_rows if l['label'] == 'TT'] )
          row['n probtt'] = len( [l for l in patch_rows if l['label'] == 'Probable TT'] )
          row['n epi'] = len( [l for l in patch_rows if l['label'] == 'Epilation'] )
          row['n probepi'] = len( [l for l in patch_rows if l['label'] == 'Probable Epilation'] )
          row['n healthy'] = len( [l for l in patch_rows if l['label'] == 'Healthy'] )
          row['n healthy'] = len( [l for l in patch_rows if l['label'] == 'Unknown'] )
        self.image_list.append(row)
      progress.setValue(len(image_list))
      logging.debug('Number of images read: {}'.format(len(self.image_list)))
      # create a time stamped temp file
      if len(self.image_list) > 0:
        csv_file_name = self.path_to_image_details.name
        from datetime import datetime
        curDTObj = datetime.now()
        datetimeStr = curDTObj.strftime("%Y%m%d_%H%M%S")
        csv_file_name = csv_file_name.replace('.csv', '_{}_{}.csv'.format(self.ui.usernameLineEdit.text, datetimeStr))
        self.tmp_csv_file_name = self.path_to_image_details.parent / csv_file_name
        fieldnames = self.image_list[0].keys()
        logging.debug('TEMP FILE NAME IS: {}'.format(self.tmp_csv_file_name))
        with open(self.tmp_csv_file_name, 'w', newline='') as fh:
          writer = DictWriter(fh, fieldnames = fieldnames)
          writer.writeheader()

  #------------------------------------------------------------------------------
    def fillMasterTable(self):
      # Assumes that the information the image_list is correct
      if self.image_list is None or len(self.image_list) == 0:
        logging.debug('Image list is empty')
        return
      checkboxKeys = ['graded', 'blurry','mislabeled']
      keys = [key for key in checkboxKeys]
      all_other = [key for key in self.image_list[0].keys() if key not in keys]
      keys.extend(all_other)
      self.ui.imageDetailsTable.enabled = 1
      for key in keys:
        self.ui.imageDetailsTable.setColumnCount(len(keys))
        self.ui.imageDetailsTable.setHorizontalHeaderLabels(keys)
        self.ui.imageDetailsTable.horizontalHeader().setVisible(True)

      for row in self.image_list:
        row_id = self.ui.imageDetailsTable.rowCount
        self.ui.imageDetailsTable.insertRow(row_id)
        for ind, key in enumerate(keys): # Get in particular oder
          if key in checkboxKeys:
            checkbox = qt.QTableWidgetItem()
            checkstate = qt.Qt.Unchecked if row[key]==0 else qt.Qt.Checked
            checkbox.setCheckState(checkstate)
            checkbox.setTextAlignment(qt.Qt.AlignCenter)
            self.ui.imageDetailsTable.setItem(row_id, ind, checkbox)
          else:
            item = qt.QTableWidgetItem("{}".format(row[key]))
            item.setTextAlignment(qt.Qt.AlignCenter)
            self.ui.imageDetailsTable.setItem(row_id, ind, item)
      self.ui.imageDetailsTable.resizeColumnsToContents()

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
    def changeCurrentImageInd(self, new_ind):
      if self.image_list is None or len(self.image_list) == 0:
        logging.debug('Image list is empty, nothing to do on image index change')
        return

      if new_ind == self.current_ind:
        logging.debug('New index the same as the old one, nothing new to do.')
        return

      if self.current_ind not in range(len(self.image_list)):
        logging.debug('The current index is not in range of image list, nothing to do here.')
      else:
        self.saveCurrentImagePatchInfo()
        self.updateMasterDictAndTable()
        self.saveCurrentRowToMaster()
      
      self.current_ind = new_ind

      if self.current_ind not in range(len(self.image_list)):
        logging.debug('The new image index is out of range, nothing to do.')
        return

      self.updateNavigationUI()
      if self.current_ind >=0 and len(self.image_list) > 0:
        self.showImageAtCurrentInd()
        self.loadCurrentSegmentation()
      self.updatePatchesTable(clearTable=True)
      self.loadExistingPatches()

    #------------------------------------------------------------------------------
    #------------------------------------------------------------------------------  
    def onImageIndexChanged(self, scroll_pos):
      logging.debug('New IND: {}, Self: {}'.format(scroll_pos-1, self.current_ind))
      self.changeCurrentImageInd(scroll_pos-1)

    #------------------------------------------------------------------------------
    #------------------------------------------------------------------------------  
    def onFindUngradedClicked(self):
      if self.image_list is not None and self.ui is not None\
        and self.current_ind in range(len(self.image_list)):
          new_ind = self.findNextNonGradedInd()
          logging.debug('New IND: {}, Self: {}'.format(new_ind, self.current_ind))
          self.ui.imageNavigationScrollBar.setValue(new_ind+1)

    #------------------------------------------------------------------------------
    #------------------------------------------------------------------------------
    def onImageDetailsRowClicked(self, item):
      if self.image_list is None or len(self.image_list) == 0 or\
        self.current_ind not in range(len(self.image_list)):
        logging.debug('Row change has no effect, no image details were found')

      row = item.row()
      col = item.column()
      if row == self.current_ind:
        self.ui.imageDetailsTable.selectRow(row)
      self.ui.imageNavigationScrollBar.setValue(row+1)
      # if self.ui is not None:
      #   self.ui.imageDetailsTable.selectRow(self.current_ind)

  ### Data processing ######
  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------  
    def getCurrentPatchFilePath(self):
      if self.image_list is not None and len(self.image_list) > 0 and self.current_ind in range( len(self.image_list)):
        patch_file_path = self.image_list[self.current_ind]['patches path']
        return patch_file_path
      else:
        return None

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------  
    def getCurrentSegmentationFilePath(self, ind=None):
      if self.image_list is not None and len(self.image_list) > 0 and (self.current_ind in range( len(self.image_list)) or ind is not None):
        if ind is None:
          ind = self.current_ind
        segmentation_file_path = self.image_list[ind]['segmentation path']
        return segmentation_file_path
      else:
        return None

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------  
    def findNextNonGradedInd(self):
      if self.image_list is None or \
          self.current_ind not in range(len(self.image_list)):
        return
      first_ind = self.current_ind
      last_ind = 0
      if 'graded' in self.image_list[first_ind].keys():
        for ind in range(first_ind+1, len(self.image_list)):
          if self.image_list[ind]['graded'] == 0:
            first_ind = ind
            break
          else:
            if ind == len(self.image_list)-1:
              slicer.util.infoDisplay("Reached the last image, All graded!!", parent=self.parent)
              first_ind = ind
      return first_ind

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------  
    def startProcessingFiles(self):
      if self.current_ind >= 0:
        self.current_ind = -1

      if len(self.image_list) > 0:
        found_at_least_one = False
        for row in self.image_list:
          image_path = row['image path']
          seg_path = row['segmentation path']
          if image_path.exists() and seg_path.exists():
            found_at_least_one = True
            break

        if found_at_least_one:
          # Find the first index of the graded.
          self.changeCurrentImageInd(0)
        else:
          slicer.util.errorDisplay("Couldn't find images from the list in directory: {}".format(self.path_to_image_details), parent=self.parent)

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------  
    def loadCurrentSegmentation(self):
      logging.debug('in loadCurrentSegmentation')
      if len(self.image_list) == 0 or self.path_to_image_details is None: 
        slicer.util.errorDisplay('Show image at current IND: Need to chose an image list and path to the images - make sure those are in', parent=self.parent)
        return
      if self.current_ind < 0 not in range(len(self.image_list)):
        slicer.util.warningDisplay("Wrong image index: {}".format(self.current_ind))
      
      imgpath = self.image_list[self.current_ind]['segmentation path']
      try:
        if self.segmentation_node is not None:
          utility.MRMLUtility.removeMRMLNode(self.segmentation_node)
          utility.MRMLUtility.removeMRMLNode(self.segmentation_editor_node)
        #utility.MRMLUtility.loadMRMLNode('image_node', self.path_to_server, self.image_list[self.current_ind] + '.jpg', 'VolumeFile') 
        # TODO: Rename the segmentations to EyeBall and Pupil

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
          if self.ui is not None:
            self.ui.SegmentEditorWidget.setEnabled(visibility)

      except Exception as e:
        slicer.util.errorDisplay("Couldn't load imagepath: {}\n ERROR: {}".format(imgpath, e), parent=self.parent)

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------  
    def showImageAtCurrentInd(self):
      logging.info('In showImageAtCurrentInd')
      if len(self.image_list) == 0 or self.path_to_image_details is None:
        slicer.util.errorDisplay('Show image at current IND: Need to chose an image list - make sure those are in', parent=self.parent)
        return
      if self.current_ind not in range(len(self.image_list)):
        slicer.util.warningDisplay("Wrong image index: {}".format(self.current_ind))

      imgpath =  self.image_list[self.current_ind]['image path']
      try:
        if self.image_node is not None:
          utility.MRMLUtility.removeMRMLNode(self.image_node)
        #utility.MRMLUtility.loadMRMLNode('image_node', self.path_to_server, self.image_list[self.current_ind] + '.jpg', 'VolumeFile') 
        self.image_node = slicer.util.loadVolume(str(imgpath), {'singleFile':True})
        slicer.util.resetSliceViews()
      except Exception as e:
        slicer.util.errorDisplay("Couldn't load imagepath: {}\n ERROR: {}".format(imgpath, e), parent=self.parent)

    #------------------------------------------------------------------------------
    def readCSV(self, file_path):
      try:
        if not file_path.exists() or file_path.suffix != '.csv':
          logging.debug('Either the file does not exist, or not csv, can;t read')
          return
        rows = []
        with open(file_path, 'r', newline='') as fh:
          reader = DictReader(fh)
          rows = [row for row in reader]
        return rows
      except IOError as e:
        logging.warning('IO Error reading the CSV FILE: {} \n {}'.format(file_path, e))
        return []
      except Exception as e:
        logging.warning('Other Error reading the CSV FILE: {} \n {}'.format(file_path, e))
        return []

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------  
    def loadExistingPatches(self):
      logging.debug('in: loadExistingPatches')
      if len(self.image_list) == 0 or \
        self.path_to_server is None or \
          self.current_ind < 0 or self.current_ind >= len(self.image_list):
        logging.info('Cannot load existincg patch info: Select a valid csv file and point to a correct folder with images')
        return

      if self.ui.imagePatchesTableWidget is None:
        logging.warning('Image Patches table is None, returning from saveCurrentImagePatchInfo')
        return

      csv_file_path = self.getCurrentPatchFilePath()
      if csv_file_path is None:
        logging.warining('Error getting the name of the patches file, returning')
        return

      if csv_file_path.exists():
        logging.info('Attempting to read existing patches file')
        try:
          rows = self.readCSV(csv_file_path)
          if len(rows) > 0:
            for row in rows:
              ijk = None
              ijk = [int(row['x']), int(row['y']), 0]
              # Adding row to the table will also update the combo box
              row_id = self.addPatchRow(ijk, label=row['label'])
              logging.debug('Added row: {}, ijk: {}, label: {}'.format(row_id, ijk, row['label']))
              logging.debug('Combobox label: {}, table label: {}'.format(self.ui.patchLabelComboBox.currentText,  self.ui.imagePatchesTableWidget.item(row_id, 1).text()))
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
                logging.debug('Combobox label: {}, table label: {}'.format(self.ui.patchLabelComboBox.currentText,  self.ui.imagePatchesTableWidget.item(row_id, 1).text()))
                self.updateFiducialSelection(row_id)
          else:
            raise IOError('Error reading the patches file')
        except IOError as e:
          logging.warning("Couldn't read the patches file {}, clearing the widget table: \n {}".format(csv_file_path, e))
          self.updatePatchesTable(clearTable=True)
        except Exception as e:
          logging.warning("Error loading existing path file {}, error: \n {} ".format(csv_file_path, e))
          self.updatePatchesTable(clearTable=True)

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------
    def writeFinalMasterCSV(self):
      if len(self.image_list) > 0 and self.path_to_server is not None:
        csv_file_name = self.path_to_image_details.name
        csv_file_name = csv_file_name.replace('.csv', '_{}.csv'.format(self.ui.usernameLineEdit.text))
        path = self.path_to_image_details.parent / csv_file_name
        try:
          with open(path, 'w', newline='') as fh:
            fieldnames = self.image_list[0].keys()
            writer = DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for listrow in self.image_list:
              row = listrow.copy()
              row['image path'] = row['image path'].relative_to(self.path_to_server)
              row['segmentation path'] = row['segmentation path'].relative_to(self.path_to_server)
              if row['patches path'].exists():
                row['patches path'] = row['patches path'].relative_to(self.path_to_server)
              else:
                row['patches path'] = ''
              writer.writerow(row)
          from shutil import copyfile
          copyfile(path, self.path_to_image_details)
        except IOError as e:
          slicer.util.errorDisplay('ERROR Writing out the master csv file.\n {}'.format(e), parent=self.parent)
        except KeyError as e:
          slicer.util.errorDisplay('Error during key parsing for the final write', parent=self.parent)

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------  
    def saveCurrentImagePatchInfo(self):
      if len(self.image_list) == 0 or \
        self.path_to_server is None or \
          self.current_ind not in range(len(self.image_list)):
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
          text = self.ui.imagePatchesTableWidget.item(row, 0).text()
          csv_row['x'] = text.split(',')[0]
          csv_row['y'] = text.split(',')[1]
          csv_row['label'] = self.ui.imagePatchesTableWidget.item(row, 1).text()
          csv_file_rows.append(csv_row)
      except Exception as e:
        logging.error('Error parsing the table widget: \n {}'.format(e))
        return
      
      if len(csv_file_rows) == 0:
        logging.info('No rows were parsed from the Patches Table, nothing to save: returning')
        return

      csv_file_path = self.getCurrentPatchFilePath()
      if csv_file_path is None:
        logging.warining('Error getting the name of the patches file, returning')
        return
      try:
        with open(csv_file_path, 'w', newline='') as fh:
          writer = DictWriter(fh, csv_file_rows[0].keys())
          writer.writeheader()
          writer.writerows(csv_file_rows)
        logging.info('Wrote the patches file: {}'.format(csv_file_path))
      except IOError as e:
        logging.error('Error writing the csv file: {} \n  {}'.format(csv_file_path, e))

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------
    def updateMasterDictAndTable(self):
      if self.image_list is None or len(self.image_list) == 0\
        or self.current_ind not in range(len(self.image_list)):
        logging.debug('Nothing to update for master table, returning')
        return

      self.image_list[self.current_ind]['n samples'] = self.ui.imagePatchesTableWidget.rowCount
      labelColumn = [ self.ui.imagePatchesTableWidget.item(row, 1).text() for row in range(self.ui.imagePatchesTableWidget.rowCount)]
      self.image_list[self.current_ind]['n tt'] = len( [row for row in labelColumn if row == 'TT'] )
      self.image_list[self.current_ind]['n probtt'] = len( [row for row in labelColumn if row == 'Probable TT'] )
      self.image_list[self.current_ind]['n epi'] = len( [row for row in labelColumn if row == 'Epilation'] )
      self.image_list[self.current_ind]['n probepi'] = len( [row for row in labelColumn if row == 'Probable Epilation'] )
      self.image_list[self.current_ind]['n healthy'] = len( [row for row in labelColumn if row == 'Healthy'] )
      self.image_list[self.current_ind]['n healthy'] = len( [row for row in labelColumn if row == 'Unknown'] )

      # Get the checkbox state.
      checkboxkeys = ['graded', 'blurry','mislabeled']
      for columnid in range(self.ui.imageDetailsTable.columnCount):
        # Save the current state of the table
        headerlabel = self.ui.imageDetailsTable.horizontalHeaderItem(columnid).text()
        if headerlabel in checkboxkeys:
          state = self.ui.imageDetailsTable.item(self.current_ind, columnid).checkState()
          self.image_list[self.current_ind][headerlabel] = 0 if state==qt.Qt.Unchecked else 1
        elif headerlabel.startswith('n '):
          self.ui.imageDetailsTable.item(self.current_ind, columnid).setText('{}'.format(self.image_list[self.current_ind][headerlabel]))

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------
    def saveCurrentRowToMaster(self):
      if self.tmp_csv_file_name is not None and \
        len(self.image_list) > 0 and \
        self.current_ind in range(len(self.image_list)):
        fieldnames = self.image_list[self.current_ind].keys()
        writeheader = False
        if not self.tmp_csv_file_name.exists():
          writeheader = True
        try:
          with open(self.tmp_csv_file_name, 'a+', newline='') as fh:
            writer = DictWriter(fh, fieldnames = fieldnames)
            if writeheader:
              writer.writeheader()
            writer.writerow(self.image_list[self.current_ind])
        except Exception as e:
          logging.warning('Error writing the row {} to csv {}'.format(self.current_ind, self.tmp_csv_file_name))

  #------------------------------------------------------------------------------
  #------------------------------------------------------------------------------  
    def updateFiducialSelection(self, row):
      logging.debug('In updatefiducial selection')
      if row not in range(self.ui.imagePatchesTableWidget.rowCount):
        return

      comboBoxLabel = self.ui.patchLabelComboBox.currentText
      tableLabel = self.ui.imagePatchesTableWidget.item(row, 1).text()
      logging.debug('Combobox label: {}, tablelabel: {}'.format(comboBoxLabel, tableLabel))
      if tableLabel != comboBoxLabel:
        all_labels = [self.ui.patchLabelComboBox.itemText(i) for i in range(self.ui.patchLabelComboBox.count)]
        if tableLabel not in all_labels:
          logging.info('During adding row to patch table at row: {}, label: {} is marked unknown'.format(row, tableLabel))
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

  #
  # TTSegToolWidget
  #

class TTSegToolWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):

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

      if not self.developerMode:
        self.launchSlicelet()
      else:
        # Show slicelet button
        showSliceletButton = qt.QPushButton("Start TT Segmentation Tool")
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
    mainFrame.setSlicelet(slicelet)
