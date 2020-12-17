from argparse import ArgumentParser
import logging
from csv import DictReader, DictWriter
from pathlib import Path
import numpy as np

from CommonUtilities import utility
import vtk, qt, ctk, slicer

def main(args):
    img_dir = Path(args.input_dir)
    if not img_dir.is_dir():
        print('Input not a directory, skipping')
    
    all_nrrds = list(img_dir.glob(*.nrrd))
    segmentation_node = None
    image_node = None

    for segpath in all_nrrds:
        imgpath = Path(args.img_dir) / segpath.name.replace('.nrrd', '.jpg')
        try:
            if segmentation_node is not None:
                slicer.mrmlScene.RemoveNode(segmentation_node)
                segmentation_node = None
            # utility.MRMLUtility.removeMRMLNode(segmentation_editor_node)
            
            segmentation_node = slicer.util.loadSegmentation(str(imgpath))
            # Deal with segment names:
            current_segmentation = segmentation_node.GetSegmentation()
            number_of_segments = current_segmentation.GetNumberOfSegments()
            
            if number_of_segments < 3:
                createEyelidSegment()
                current_segmentation = segmentation_node.GetSegmentation()
                number_of_segments = current_segmentation.GetNumberOfSegments()
            else:
            showProgress( 50, "Setting up segment name")
            setSegmentationLabelNames()

            showProgress(90, "Setting up editors")
            if ui is not None and editor is not None:
            selectParameterNode()
            updateEditorSources()
            if ui is not None and editor is not None:
                editor.setEnabled(segmentEditModeOn)
        except Exception as e:
            slicer.util.errorDisplay("Couldn't load segmentation: {}\n ERROR: {}".format(imgpath, e))
            segmentation_node = None
        slicer.progressWindow.close()

        def createEyelidSegment(self):
        if segmentation_node is None or image_node is None:
            return

        current_segmentation = segmentation_node.GetSegmentation()
        number_of_segments = current_segmentation.GetNumberOfSegments()
        if number_of_segments > 2:
            # Most probably has an eyelid already, return
            return

        # Export segment as vtkImageData (via temporary labelmap volume node)
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
        setSegmentationLabelNames()
        
        # Save this label to image
        old_state = save_segmentation_flag
        save_segmentation_flag = True
        saveCurrentSegmentation()
        save_segmentation_flag = old_state
        
        slicer.mrmlScene.RemoveNode(labelmapVolumeNode.GetDisplayNode().GetColorNode())
        slicer.mrmlScene.RemoveNode(labelmapVolumeNode)
        slicer.mrmlScene.RemoveNode(clone.GetDisplayNode().GetColorNode())
        slicer.mrmlScene.RemoveNode(clone)



if __name__=="__main__":
# /Users/hinashah/famli/Groups/Restricted_access_data/Clinical_Data/EPIC/Dataset_B
    parser = ArgumentParser()
    parser.add_argument('--input_dir', type=str, help='Input directory with all segmentations')
    parser.add_arguemtn('--ref_img_dir', type=str, help = 'Input directory for reference images')
    parser.add_argument('--out_dir', type=str, help='Output directory to save the new segmentations to')
    args = parser.parse_args()

    main(args)