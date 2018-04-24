import os
import sys
module_path = os.path.abspath(os.path.join('/home/vijin/iith/project/workpad/ssd.pytorch'))
if module_path not in sys.path:
    sys.path.append(module_path)
import torch
import torch.nn as nn
import torch.backends.cudnn as cudnn
import torchvision.transforms as transforms
from torch.autograd import Variable
import cv2
import pickle
import numpy as np

from ssd import build_ssd
from data import v2, v1, AnnotationTransform, MiniDroneDataset, detection_collate, OkutamaDataset
from utils.augmentations import SSDAugmentation

# calculate IOU
def bb_intersection_over_union(boxA, boxB):
    # determine the (x, y)-coordinates of the intersection rectangle
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    # compute the area of intersection rectangle
    interArea = (xB - xA + 1) * (yB - yA + 1)

    # compute the area of both the prediction and ground-truth
    # rectangles
    boxAArea = (boxA[2] - boxA[0] + 1) * (boxA[3] - boxA[1] + 1)
    boxBArea = (boxB[2] - boxB[0] + 1) * (boxB[3] - boxB[1] + 1)

    # compute the intersection over union by taking the intersection
    # area and dividing it by the sum of prediction + ground-truth
    # areas - the interesection area
    iou = interArea / float(boxAArea + boxBArea - interArea)

    # return the intersection over union value
    return iou

# calculate TP,FP,FN from predictions and groundtruth
def calculate_metrics(ground_truths, predictions, iou_threshold = 0.5):
    '''
    NOTE:
    if in one image, we have multiple proposals for a particular object that is considered truly classified, 
    we only count one proposal as TP, and the others as FP

    ground_truths : list of ground_truth in form of tuples (xmin,ymin,xmax,ymax)
    predictions : list of prediction in form of tuples (xmin,ymin,xmax,ymax)
    '''
    TP = 0
    FP = 0
    FN = 0
    pred_found_map = {i : False for i in range(len(ground_truths))}
    if len(ground_truths) > 0:
        if len(predictions) > 0:
            for pred in predictions:
                pred_found = False
                for index, gt in enumerate(ground_truths):
                    iou = bb_intersection_over_union(pred, gt)
                    # print('IOU : {0}'.format(iou))
                    if iou > iou_threshold:
                        if pred_found_map[index] == False:
                            TP = TP + 1
                            pred_found = True
                            pred_found_map[index] = True
                            break
                if pred_found == False:
                    FP = FP + 1

            if (len(ground_truths) - len(predictions)) > 0:
                FN = FN + len(ground_truths) - len(predictions)
        else:
            FN = FN + len(ground_truths)
    else:
        if len(predictions) > 0:
            FP = FP + len(predictions)
    
    return (TP, FP, FN)

def calculate_metrics_for_image(image_index, model, img_file, ground_truth, cuda=False, person_class_index=15):
    '''
    Model will give all detections. We are only interested in person, person class index : 15
    '''
    # TO DO : basic function args validation
    
    # read image and corresponding annotations
    rgb_image = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    height, width, channels = img.shape

    # subtracting mean from three channels
    x = cv2.resize(img, (300, 300)).astype(np.float32) # input dimensions used
    x -= (104.0, 117.0, 123.0) # mean of trained model
    x = x.astype(np.float32)
    x = x[:, :, ::-1].copy()
    x = torch.from_numpy(x).permute(2, 0, 1)

    # detections
    xx = Variable(x.unsqueeze(0)) 
    if cuda:
        xx = xx.cuda()
    detections = model(xx).data

    # Contains array of [probabilty, xmin, ymin, xmax, ymax]
    person_detections = detections[0, person_class_index, :]

    # scale back to original size
    scale = torch.Tensor(rgb_image.shape[1::-1]).repeat(2)

    # create array of predictions with confidence
    predictions_conf_list = []
    predictions_list = []

    # iterate through the predicted detections
    for i in range(person_detections.size(1)):
        if person_detections[i][0] > 0.5:
            predictions_conf_list.append((person_detections[i][0], (person_detections[i,1:] * scale).cpu().numpy()))
            predictions_list.append((person_detections[i,1:] * scale).cpu().numpy())

    TP, FP, FN = calculate_metrics([list(gt[0:4]) for gt in ground_truth], predictions_list)
    predict_dict = {'ground_truth' : [list(gt[0:4]) for gt in ground_truth], 'prediction' : predictions_list, 'tp' : TP, 'fp' : FP, 'fn' : FN}
    # print('TP: {0}, FP: {1}, FN: {2}'.format(TP, FP, FN))
    return (TP, FP, FN, predict_dict)


result_folder = '/home/vijin/iith/project/workpad/results/2class_SSD300_mini_drone_40000itr'
cuda = True
# Load pretrained SSD model
net = build_ssd('test', 300, 2)    # initialize SSD

#net.load_weights('/home/vijin/iith/project/workpad/ssd.pytorch/weights/ssd300_0712_115000.pth')
#net.load_weights('/home/vijin/iith/project/workpad/ssd.pytorch/weights/ssd300_mAP_77.43_v2.pth')
net.load_weights('/home/vijin/iith/project/workpad/ssd.pytorch/weights/ssd300_2class40000.pth')

if cuda:
    net.cuda()

# initialize metrics
TP_fin = 0
FP_fin = 0
FN_fin = 0


ssd_dim = 300
means = (104, 117, 123)
voc_class_map = {'Person' :1}

testset = MiniDroneDataset('//home/vijin/iith/project/data/mini-drone-data/DroneProtect-testing-set/metadata.csv', 
    '/home/vijin/iith/project/data/mini-drone-data/DroneProtect-testing-set/frames', '/home/vijin/iith/project/data/mini-drone-data/DroneProtect-testing-set/annotations',
     AnnotationTransform(voc_class_map), SSDAugmentation(ssd_dim, means))

# testset = OkutamaDataset('/home/vijin/iith/project/data/okutama-action-drone-data/test_metadata.csv', 
#      '/home/vijin/iith/project/data/okutama-action-drone-data/frames', 
#      '/home/vijin/iith/project/data/okutama-action-drone-data/annotations',
#       AnnotationTransform(voc_class_map), SSDAugmentation(ssd_dim, means))

num_images = len(testset)
pred_dict = {}

for i in range(num_images):
    print('Testing image {:d}/{:d}....'.format(i+1, num_images))
    img, image_name = testset.pull_image(i)
    groundtruth = testset.pull_annotation(i)
    TP, FP, FN, pred_obj= calculate_metrics_for_image(i, net, img, groundtruth, cuda, 1)
    pred_dict[i] = pred_obj
    print(TP,FP,FN)
    TP_fin += TP
    FP_fin += FP
    FN_fin += FN


# Pickle prediction details as obj for further error analysis
with open('{0}/pred_details.pkl'.format(result_folder), 'wb') as fp:
	pickle.dump(pred_dict, fp)

# Average Precision & Recall 
AP = TP_fin/(TP_fin+FP_fin) 
Recall = TP_fin/(TP_fin+FN_fin)

fp1 = open('{0}/eval.txt'.format(result_folder), 'w')
fp1.write('Average Precision@0.5 : {0}%\n'.format(AP * 100))
fp1.write('Average Recall@0.5 : {0}%\n'.format(Recall * 100))
fp1.write('F1 Score@0.5 : {0}%\n'.format((2* AP * Recall) / (AP + Recall)))
fp1.close()

print('AP@0.5 : {0}%'.format(AP*100))
print('Recall@0.5 : {0}%'.format(Recall * 100))
print('F1 Score@0.5 : {0}'.format((2* AP * Recall) / (AP + Recall)))