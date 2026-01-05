import torch
import numpy as np
from torchvision import transforms
from PIL import Image as PILImage
from model_1 import Finetunemodel
import os

# Load model ONCE (avoid reloading in each call)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
# Get the absolute path of the script's directory
script_dir = os.path.dirname(os.path.realpath(__file__))

# Load the model using the absolute path
weights_path = os.path.join(script_dir, "weights", "Model_V1.pt")
model = Finetunemodel(weights_path)

#model = Finetunemodel("./weights/difficult.pt").to(device)
model.eval()

def process_image(image_array):
    """ Process an image using the deep learning model. """
    image = PILImage.fromarray(image_array)  # Convert NumPy array to PIL
    transform = transforms.ToTensor()
    input_tensor = transform(image).unsqueeze(0).to(device)  # Convert to tensor

    with torch.no_grad():
        output = model(input_tensor)  # Run inference
        
    if isinstance(output, tuple):
        processed_image = output[1]  # Use second value if tuple
    else:
        processed_image = output  # Directly use if not a tuple

    # Convert back to NumPy array
    processed_image_numpy = processed_image[0].cpu().float().numpy()
    processed_image_numpy = np.transpose(processed_image_numpy, (1, 2, 0))
    processed_image_numpy = np.clip(processed_image_numpy * 255.0, 0, 255.0).astype(np.uint8)

    #print("fdsfadfg")
    #print("Final Output Shape:", processed_image_numpy.shape)
    return np.ascontiguousarray(processed_image_numpy)  # Return NumPy array

#dummy_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8) 
#output_image = process_image(dummy_image)
#print("Final Output Shape:", output_image.shape)
#print("Final Output Type:", type(output_image))
#print("Final Output DType:", output_image.dtype)
