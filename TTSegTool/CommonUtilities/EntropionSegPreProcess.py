from argparse import ArgumentParser
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
    segment_label_names = {1:'EyeBall', 2:'Cornea', 3:'EyeLid', 4:'Entropion'}
    for segment_number in range(number_of_segments):
        label = current_segmentation.GetNthSegment(segment_number).GetLabelValue()
        name = current_segmentation.GetNthSegment(segment_number).GetName()
        if label in segment_label_names and name != segment_label_names[label]:
            current_segmentation.GetNthSegment(segment_number).SetName(segment_label_names[label])


def createEntropionSegment(segmentation_node, ref_img_path, out_segmentation_path):
    if segmentation_node is None or not ref_img_path.exists():
        print('Could not find: {}'.format(ref_img_path))
        return

    current_segmentation = segmentation_node.GetSegmentation()
    number_of_segments = current_segmentation.GetNumberOfSegments()
    if number_of_segments > 3:
        # Most probably has an entropion already, return
        return

    # Export segment as vtkImageData (via temporary labelmap volume node)
    image_node = slicer.util.loadVolume(str(ref_img_path), {'singleFile':True})
    segmentIds = vtk.vtkStringArray()
    current_segmentation.GetSegmentIDs(segmentIds)
    segmentIds.InsertNextValue('Entropion')
    segmentation_node.GetSegmentation().AddEmptySegment('Entropion')
    
    # Save this label to image
    slicer.util.saveNode(segmentation_node, str(out_segmentation_path))
    
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

    out_csv_file = Path(input_csv.replace('.csv', '_entropion.csv'))
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
                
                if number_of_segments < 4:
                    createEntropionSegment(segmentation_node, imgpath, out_segmentation_path)
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
    input_csv = "P:/hinashah/segapplist_all_manual_segmentation.csv"
    out_dir = "P:/hinashah/test/Segmentations_Entropion"
    server_path = "P:/"
    main(input_csv, out_dir, server_path)