from argparse import ArgumentParser
import logging
from csv import DictReader, DictWriter
from pathlib import Path
import numpy as np

from CommonUtilities import utility
import vtk, qt, ctk, slicer



def setSegmentationLabelNames(segmentation_node):
    if segmentation_node is None:
        return

    current_segmentation = segmentation_node.GetSegmentation()
    number_of_segments = current_segmentation.GetNumberOfSegments()
    segment_label_names = {1:'EyeBall', 2:'Cornea', 3:'EyeLid'}
    for segment_number in range(number_of_segments):
        label = current_segmentation.GetNthSegment(segment_number).GetLabelValue()
        name = current_segmentation.GetNthSegment(segment_number).GetName()
        if label in segment_label_names and name != segment_label_names[label]:
            current_segmentation.GetNthSegment(segment_number).SetName(segment_label_names[label])


def createEyelidSegment(segmentation_node, ref_img_path, out_segmentation_path):
    if segmentation_node is None or not ref_img_path.exists():
        print('Could not find: {}'.format(ref_img_path))
        return

    current_segmentation = segmentation_node.GetSegmentation()
    number_of_segments = current_segmentation.GetNumberOfSegments()
    if number_of_segments > 2:
        # Most probably has an eyelid already, return
        return

    # Export segment as vtkImageData (via temporary labelmap volume node)
    image_node = slicer.util.loadVolume(str(ref_img_path), {'singleFile':True})
    segmentIds = vtk.vtkStringArray()
    current_segmentation.GetSegmentIDs(segmentIds)
    labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode')
    slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(segmentation_node, segmentIds, labelmapVolumeNode, image_node, slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY )
    # Manipulate the mask values to add the third label
    mask = slicer.util.arrayFromVolume(labelmapVolumeNode)
    newmask = mask.copy()
    newmask[newmask > 0] = mask.max() + 1
    clone = slicer.modules.volumes.logic().CloneVolume(labelmapVolumeNode, "CloneLabelMap")
    slicer.util.updateVolumeFromArray(clone, newmask)
    segmentImageData = clone.GetImageData()
    kernelSize = [20, 200, 1]
    erodeDilate = vtk.vtkImageDilateErode3D()
    erodeDilate.SetInputData(segmentImageData)
    erodeDilate.SetDilateValue(mask.max() + 1)
    erodeDilate.SetErodeValue(0)
    erodeDilate.SetKernelSize(*kernelSize)
    erodeDilate.Update()
    segmentImageData.DeepCopy(erodeDilate.GetOutput())
    newmask = slicer.util.arrayFromVolume(clone)
    # Combine both the masks together to add the new labelmap.
    newmask[mask > 0] = 0
    newmask = newmask + mask
    slicer.util.updateVolumeFromArray(clone, newmask)
    segmentIds.InsertNextValue('EyeLid')
    segmentation_node.GetSegmentation().AddEmptySegment('EyeLid')
    slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(clone, segmentation_node, segmentIds)
    setSegmentationLabelNames(segmentation_node)
    
    # Save this label to image
    slicer.util.saveNode(clone, str(out_segmentation_path))
    slicer.mrmlScene.RemoveNode(labelmapVolumeNode.GetDisplayNode().GetColorNode())
    slicer.mrmlScene.RemoveNode(labelmapVolumeNode)
    slicer.mrmlScene.RemoveNode(clone.GetDisplayNode().GetColorNode())
    slicer.mrmlScene.RemoveNode(clone)
    slicer.mrmlScene.RemoveNode(image_node)

def writeToCsv(out_path, fieldnames, row=None):
    mode = 'w' if row is None else 'a+'
    with open(out_path, mode, newline='') as fh:
        dictwriter = DictWriter(fh, fieldnames)
        if row is None:
            dictwriter.writeheader()
        else:
            dictwriter.writerow(row)

def main(input_csv, out_dir, server_path):
    try:
        with open( Path(input_csv), 'r') as fh:
            reader = DictReader(fh)
            all_rows = [row for row in reader]
    except Exception as e:
        print('error reading the master dict file, return: {}'.format(e))
        return

    out_csv_file = Path(input_csv.replace('.csv', '_eyelid.csv'))
    fieldnames = all_rows[0].keys()
    writeToCsv(out_csv_file, fieldnames)

    segmentation_node = None
    image_node = None

    slicer.progressWindow = qt.QProgressDialog("Ploughing throug segmentations", "Abort Load", 0, len(all_rows), slicer.util.mainWindow())
    slicer.progressWindow.setWindowModality(qt.Qt.WindowModal)
    def showProgress(value, text):
        if slicer.progressWindow.wasCanceled:
            raise Exception('Segmentation load aborted')
        slicer.progressWindow.show()
        slicer.progressWindow.activateWindow()
        slicer.progressWindow.setValue(value)
        slicer.progressWindow.setLabelText(text)
        slicer.app.processEvents()
        
    for num_id, row in enumerate(all_rows):
        imgpath = Path(server_path)/Path(row['image path'])
        segpath = Path(server_path)/Path(row['segmentation path'])
        showProgress(num_id, str(segpath))
        if not segpath.exists() or not imgpath.exists():
            print('Either {} or {} does not exists'.format(imgpath, segpath))
            continue
        out_segmentation_path = Path(out_dir) / segpath.name
        try:
            if segmentation_node is not None:
                slicer.mrmlScene.RemoveNode(segmentation_node)
                segmentation_node = None
            
            if not out_segmentation_path.exists():
                segmentation_node = slicer.util.loadSegmentation(str(segpath))
                # Deal with segment names:
                current_segmentation = segmentation_node.GetSegmentation()
                number_of_segments = current_segmentation.GetNumberOfSegments()
                
                if number_of_segments < 3:
                    createEyelidSegment(segmentation_node, imgpath, out_segmentation_path)
                    current_segmentation = segmentation_node.GetSegmentation()
                    number_of_segments = current_segmentation.GetNumberOfSegments()
                    row['segmentation path'] = out_segmentation_path.relative_to(server_path)
            else:
                print('{} already exists, skipping processing'.format(out_segmentation_path))
                row['segmentation path'] = out_segmentation_path.relative_to(server_path)
            writeToCsv(out_csv_file, fieldnames, row=row)
        except Exception as e:
            print("Couldn't load segmentation: {}\n ERROR: {}".format(segpath, e))
            segmentation_node = None
    slicer.progressWindow.close()

if __name__=="__main__":
# /Users/hinashah/famli/Groups/Restricted_access_data/Clinical_Data/EPIC/Dataset_B
    # parser = ArgumentParser()
    # parser.add_argument('--input_dir', type=str, help='Input directory with all segmentations')
    # parser.add_arguemtn('--ref_img_dir', type=str, help = 'Input directory for reference images')
    # parser.add_argument('--out_dir', type=str, help='Output directory to save the new segmentations to')
    # args = parser.parse_args()
    
    # print('Trying something')
    input_csv = "P:/hashiya/trachoma_sev3_epi0_patcheslist_Hashiya.csv"
    out_dir = "P:/hashiya/Segmentations_Hashiya"
    server_path = "P:/"
    main(input_csv, out_dir, server_path)