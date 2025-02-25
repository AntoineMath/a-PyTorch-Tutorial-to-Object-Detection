import argparse
from tqdm import tqdm
import torchvision.transforms.functional as FT
import torch
from utils import rev_label_map, label_color_map, resize
from PIL import ImageDraw, ImageFont
from datasets import DetectDataset, ThermalDataset

parser = argparse.ArgumentParser()
parser.add_argument("test_data", type=str, help="path to a Serie containing images/ and images_8bit/ folder")
#parser.add_argument("img_type", help="type of image to detect, either 'thermal' or 'depth'", type=str)
parser.add_argument("weights", type=str, help="path to the weights.pth.tar file")
#parser.add_argument("train_data", type=str, help="path to the train_data folder containing .json files used for training the model")
parser.add_argument('-k', "--top_k", type=int, default=1, help="show the best k detections per image")
parser.add_argument('--min_score', type=float, default=0.01, help="minimum score to consider a detection")
parser.add_argument("--max_overlap", type=float, default=0.45, help="limit of overlapping beyond which we consider there is only one object")
args = parser.parse_args()

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

#training_set = ThermalDataset(args.train_data, img_type=args.img_type, split='train')
#mean, std = training_set.dataset_mean, training_set.dataset_std

detect_dataset = DetectDataset(args.test_data)
detect_loader = torch.utils.data.DataLoader(detect_dataset, batch_size=1, shuffle=False)

checkpoint = torch.load(args.weights)
start_epoch = checkpoint['epoch'] + 1
best_loss = checkpoint['best_loss']
print('\nLoaded checkpoint from epoch %d. Best loss so far is %.3f.\n' % (start_epoch, best_loss))
model = checkpoint['model']
model = model.to(device)
model.eval()


def detect(detect_loader, min_score, max_overlap, top_k, suppress=None):
    """
    Detect objects in an image with a trained SSD300, and visualize the results.

    :param detect_loader: data loader which casts images of the specified dataset
    :param min_score: minimum threshold for a detected box to be considered a match for a certain class
    :param max_overlap: maximum overlap two boxes can have so that the one with the lower score is not suppressed via Non-Maximum Suppression (NMS)
    :param top_k: if there are a lot of resulting detection across all classes, keep only the top 'k'
    :param suppress: classes that you know for sure cannot be in the image or you do not want in the image, a list
    :return: annotated image, a PIL Image
    """

    for i, (image, image_8bit, original_width, original_height) in enumerate(tqdm(detect_loader, desc='detection')):

        image_8bit = FT.to_pil_image(image_8bit)

        image = image.to(device)  # (1, 1, 300, 300)

        # Forward prop.
        predicted_locs, predicted_scores = model(image)

        # Detect objects in SSD output
        det_boxes, det_labels, det_scores = model.detect_objects(predicted_locs, predicted_scores, min_score=min_score,
                                                                 max_overlap=max_overlap, top_k=top_k)

        # Move detections to the CPU
        det_boxes = det_boxes[0].to('cpu')

        # Transform to original image dimensions
        original_dims = torch.FloatTensor(
            [original_width, original_height, original_width, original_height]).unsqueeze(0)
        #det_boxes = det_boxes * original_dims
        det_boxes = det_boxes * 300

        # Decode class integer labels
        det_labels = [rev_label_map[l] for l in det_labels[0].to('cpu').tolist()]

        # If no objects found, the detected labels will be set to ['0.'], i.e. ['background'] in SSD300.detect_objects() in model.py
        if det_labels == ['background']:
            # Just return original image
            image_8bit.show()
            print('background')
            input('Press Enter to detect next image')
            continue


        # Annotate
        annotated_image = image_8bit
        annotated_image, _ = resize(annotated_image, boxes=torch.Tensor([0, 0, 0, 0]), dims=(300, 300))
        draw = ImageDraw.Draw(annotated_image)
        font = ImageFont.load_default()

        # Suppress specific classes, if needed
        for i in range(det_boxes.size(0)):
            if suppress is not None:
                if det_labels[i] in suppress:
                    continue

            # Boxes
            box_location = det_boxes[i].tolist()
            draw.rectangle(xy=box_location, outline=label_color_map[det_labels[i]])
            draw.rectangle(xy=[l + 1. for l in box_location], outline=label_color_map[
                det_labels[i]])  # a second rectangle at an offset of 1 pixel to increase line thickness
            # draw.rectangle(xy=[l + 2. for l in box_location], outline=label_color_map[
            #     det_labels[i]])  # a third rectangle at an offset of 1 pixel to increase line thickness
            # draw.rectangle(xy=[l + 3. for l in box_location], outline=label_color_map[
            #     det_labels[i]])  # a fourth rectangle at an offset of 1 pixel to increase line thickness

            # Text
            text_size = font.getsize(det_labels[i].upper())
            text_location = [box_location[0] + 2., box_location[1] - text_size[1]]
            textbox_location = [box_location[0], box_location[1] - text_size[1], box_location[0] + text_size[0] + 4.,
                                box_location[1]]
            draw.rectangle(xy=textbox_location, fill=label_color_map[det_labels[i]])
            draw.text(xy=text_location, text=det_labels[i].upper(), fill='white',
                      font=font)
        del draw
        annotated_image.show()
        print('score:', det_scores)
        input('Press Enter to detect next image')


if __name__ == '__main__':

    result = detect(detect_loader, min_score=args.min_score, max_overlap=args.max_overlap, top_k=args.top_k)


