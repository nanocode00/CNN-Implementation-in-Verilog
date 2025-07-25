############# MNIST Data Set Load & CNN Implementation ####################

# Reference : https://github.com/pytorch/examples/blob/master/mnist/main.py

from __future__ import print_function
import argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torch.quantization
from torchvision import datasets, transforms
from torch.autograd import Variable
import numpy as np

torch.backends.quantized.engine = 'fbgemm'

batch_size = 64

# MNIST Dataset
train_dataset = datasets.MNIST(root='./data/',
                                train=True,
                                transform=transforms.ToTensor(),
                                download=True)
test_dataset = datasets.MNIST(root='./data/',
                                train=False,
                                transform=transforms.ToTensor())

# Data Loader (Input Pipeline)
train_loader = torch.utils.data.DataLoader(dataset=train_dataset,
                                            batch_size=batch_size,
                                            shuffle=True)

test_loader = torch.utils.data.DataLoader(dataset=test_dataset,
                                            batch_size=batch_size,
                                            shuffle=False)

# CNN class
class CNN(nn.Module):
    
    # Initialization
    def __init__(self):
        super (CNN, self).__init__()

        self.quant = torch.quantization.QuantStub()
        self.dequant = torch.quantization.DeQuantStub()
        
        self.conv1_out_np = np.zeros((1, 3, 24, 24))
        self.mp1_out_np = np.zeros((1, 3, 12, 12))
        self.conv2_out_np = np.zeros((1, 3, 8, 8))
        self.mp2_out_np = np.zeros((1, 3, 4, 4))
        self.fc_in_np = np.zeros((1, 48))
        self.fc_out_np = np.zeros((1, 10))
        
        # 1st Convolution Layer
        # Image Input Shape -> (28, 28, 1)
        # Convolution Layer -> (24, 24, 3)
        # Pooling Max Layer -> (12, 12, 3)
        self.conv1 = nn.Conv2d(1, 3, kernel_size=5)
        
        # 2nd Convolution Layer
        # Image Input Shape -> (12, 12, 3)
        # Convolution Layer -> (8, 8, 3)
        # pooling Max Layer -> (4, 4, 3)
        self.conv2 = nn.Conv2d(3, 3, kernel_size=5)
        
        # Max Pooling Layer
        self.mp = nn.MaxPool2d(2)
        
        # Fully Connected Layer
        # Num of Weight = 480
        self.fc_1 = nn.Linear(48, 10)
        
    def forward(self, x):
        in_size = x.size(0)
        
        x = self.quant(x)

        # Layer Integration
        x = self.conv1(x)
        if x.is_quantized:
            self.conv1_out_np = x.dequantize().numpy()
        else:
            self.conv1_out_np = x.detach().numpy()
        
        x = F.relu(self.mp(x))
        if x.is_quantized:
            self.mp1_out_np = x.dequantize().numpy()
        else:
            self.mp1_out_np = x.detach().numpy()

        x = self.conv2(x)
        if x.is_quantized:
            self.conv2_out_np = x.dequantize().numpy()
        else:
            self.conv2_out_np = x.detach().numpy()
        
        x = F.relu(self.mp(x))
        if x.is_quantized:
            self.mp2_out_np = x.dequantize().numpy()
        else:
            self.mp2_out_np = x.detach().numpy()
        
        # Flatten Layer
        x = x.reshape(in_size, -1)
        if x.is_quantized:
            self.fc_in_np = x.dequantize().numpy()
        else:
            self.fc_in_np = x.detach().numpy()
        
        # Fully Connected Layer
        x = self.fc_1(x)
        if x.is_quantized:
            self.fc_out_np = x.dequantize().numpy()
        else:
            self.fc_out_np = x.detach().numpy()

        x = self.dequant(x)
        
        return F.log_softmax(x)
    
# Instantiation    
model = CNN()

optimizer = optim.SGD(model.parameters(), lr=0.01, momentum=0.5)

# Training
def train(epoch):
    model.train()
    
    for batch_idx, (data, target) in enumerate(train_loader):
        
        data, target = Variable(data), Variable(target)
        
        optimizer.zero_grad()
        
        # Ouput of feedforwarding
        output = model(data)
        
        # Loss calibration
        loss = F.nll_loss(output, target)
        
        # Gradient
        loss.backward()
        
        # Back propagation
        optimizer.step()
        
        if batch_idx % 10 == 0:
            print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                epoch, batch_idx * len(data), len(train_loader.dataset),
                100. * batch_idx / len(train_loader), loss.item()))

# Test
def test():
    model.eval()

    test_loss = 0
    correct = 0
    
    for data, target in test_loader:

        data, target = Variable(data, volatile=True), Variable(target)
        
        # Output of feedforwarding
        output = model(data)
        
        test_loss += F.nll_loss(output, target, size_average=False).item()
        
        pred = output.data.max(1, keepdim=True)[1]
        correct += pred.eq(target.data.view_as(pred)).cpu().sum()
          
    test_loss /= len(test_loader.dataset)
    print('\nTest set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)\n'.format(
        test_loss, correct, len(test_loader.dataset),
        100. * correct / len(test_loader.dataset)))
    
for epoch in range(1, 10):
    train(epoch)
    test()

model.qconfig = torch.quantization.get_default_qconfig('fbgemm')
torch.quantization.prepare(model, inplace=True)

for i, (data, _) in enumerate(train_loader):
    model(data)
    if i > 5: break

model = torch.quantization.convert(model, inplace=False)

from PIL import Image

def sample_test():

    model.eval()

    test_loss = 0
    correct = 0
    
    target = Variable(torch.tensor([0]))
    
    # data (0_0.bmp)
    img = Image.open("./bmp/train_0.bmp", "r")
    np_img = np.array(img)
    np_img_re = np.reshape(np_img, (1,1,28,28))
    
    # 0 - 255 => 0 - 1 로 정규화, np.array => tensor 변환
    data = Variable(torch.tensor((np_img_re / 255), dtype = torch.float32))
    
    # Output of feedforwarding
    output = model(data)
    
    test_loss += F.nll_loss(output, target, reduction='sum').item()
    
    pred = output.data.max(1, keepdim=True)[1]
    
    correct += pred.eq(target.data.view_as(pred)).cpu().sum()
    print(correct)
    
    
sample_test()


#################### Weight & Bias in HEX of Convolution Layer1 ####################

# Calibration
int_conv1_weight = model.conv1.weight().int_repr()
int_conv1_weight_1 =  int_conv1_weight[0][0].to(torch.int32)
int_conv1_weight_2 =  int_conv1_weight[1][0].to(torch.int32)
int_conv1_weight_3 =  int_conv1_weight[2][0].to(torch.int32)

scale_conv1 = model.conv1.scale
scale_input_conv1 = model.quant.scale
bias_float_conv1 = model.conv1.bias().detach()
int_conv1_bias = (bias_float_conv1 / (scale_input_conv1 * scale_conv1)).to(torch.int32)

print("Signed")
print(int_conv1_weight_1)
print(int_conv1_weight_2)
print(int_conv1_weight_3)
print(int_conv1_bias)

# 2's Complement
for i in range(5):
    for j in range(5):
        if int_conv1_weight_1[i][j] < 0:
            int_conv1_weight_1[i][j] += 256
        if int_conv1_weight_2[i][j] < 0:
            int_conv1_weight_2[i][j] += 256
        if int_conv1_weight_3[i][j] < 0:
            int_conv1_weight_3[i][j] += 256

for k in range(3):
    if int_conv1_bias[k] < 0:
            int_conv1_bias[k] += 256

print ("Unsigned")
print(int_conv1_weight_1)
print(int_conv1_weight_2)
print(int_conv1_weight_3)
print(int_conv1_bias)

np.savetxt('txt_quantized/conv1_weight_1.txt', int_conv1_weight_1, fmt='%1.2x',delimiter = " ")
np.savetxt('txt_quantized/conv1_weight_2.txt', int_conv1_weight_2, fmt='%1.2x',delimiter = " ")
np.savetxt('txt_quantized/conv1_weight_3.txt', int_conv1_weight_3, fmt='%1.2x',delimiter = " ")
np.savetxt('txt_quantized/conv1_bias.txt', int_conv1_bias, fmt='%1.2x',delimiter = " ")

#################### Weight & Bias in HEX of Convolution Layer2 ####################

# Calibration
# print(np.shape(model.conv2.weight))

int_conv2_weight = model.conv2.weight().int_repr()

int_conv2_weight_11 =  int_conv2_weight[0][0].to(torch.int32)
int_conv2_weight_12 =  int_conv2_weight[0][1].to(torch.int32)
int_conv2_weight_13 =  int_conv2_weight[0][2].to(torch.int32)

int_conv2_weight_21 =  int_conv2_weight[1][0].to(torch.int32)
int_conv2_weight_22 =  int_conv2_weight[1][1].to(torch.int32)
int_conv2_weight_23 =  int_conv2_weight[1][2].to(torch.int32)

int_conv2_weight_31 =  int_conv2_weight[2][0].to(torch.int32)
int_conv2_weight_32 =  int_conv2_weight[2][1].to(torch.int32)
int_conv2_weight_33 =  int_conv2_weight[2][2].to(torch.int32)

scale_conv2 = model.conv2.scale
scale_input_conv2 = model.mp1_out_np.max() / 127.0
bias_float_conv2 = model.conv2.bias().detach()
int_conv2_bias = (bias_float_conv2 / (scale_input_conv2 * scale_conv2)).to(torch.int32)

print ("Signed")
print(int_conv2_weight_11)
print(int_conv2_weight_12)
print(int_conv2_weight_13, '\n')

print(int_conv2_weight_21)
print(int_conv2_weight_22)
print(int_conv2_weight_23, '\n')

print(int_conv2_weight_31)
print(int_conv2_weight_32)
print(int_conv2_weight_33, '\n')

print(int_conv2_bias)


# 2's Complement
for i in range(5):
    for j in range(5):
        if int_conv2_weight_11[i][j] < 0:
            int_conv2_weight_11[i][j] += 256
        if int_conv2_weight_12[i][j] < 0:
            int_conv2_weight_12[i][j] += 256
        if int_conv2_weight_13[i][j] < 0:
            int_conv2_weight_13[i][j] += 256
            
        if int_conv2_weight_21[i][j] < 0:
            int_conv2_weight_21[i][j] += 256
        if int_conv2_weight_22[i][j] < 0:
            int_conv2_weight_22[i][j] += 256
        if int_conv2_weight_23[i][j] < 0:
            int_conv2_weight_23[i][j] += 256
            
        if int_conv2_weight_31[i][j] < 0:
            int_conv2_weight_31[i][j] += 256
        if int_conv2_weight_32[i][j] < 0:
            int_conv2_weight_32[i][j] += 256
        if int_conv2_weight_33[i][j] < 0:
            int_conv2_weight_33[i][j] += 256

for k in range(3):
    if int_conv2_bias[k] < 0:
            int_conv2_bias[k] += 256

print ("Unsigned")
print(int_conv2_weight_11)
print(int_conv2_weight_12)
print(int_conv2_weight_13, '\n')

print(int_conv2_weight_21)
print(int_conv2_weight_22)
print(int_conv2_weight_23, '\n')

print(int_conv2_weight_31)
print(int_conv2_weight_32)
print(int_conv2_weight_33, '\n')

print(int_conv2_bias)

np.savetxt('txt_quantized/conv2_weight_11.txt', int_conv2_weight_11, fmt='%1.2x',delimiter = " ")
np.savetxt('txt_quantized/conv2_weight_12.txt', int_conv2_weight_12, fmt='%1.2x',delimiter = " ")
np.savetxt('txt_quantized/conv2_weight_13.txt', int_conv2_weight_13, fmt='%1.2x',delimiter = " ")

np.savetxt('txt_quantized/conv2_weight_21.txt', int_conv2_weight_21, fmt='%1.2x',delimiter = " ")
np.savetxt('txt_quantized/conv2_weight_22.txt', int_conv2_weight_22, fmt='%1.2x',delimiter = " ")
np.savetxt('txt_quantized/conv2_weight_23.txt', int_conv2_weight_23, fmt='%1.2x',delimiter = " ")

np.savetxt('txt_quantized/conv2_weight_31.txt', int_conv2_weight_31, fmt='%1.2x',delimiter = " ")
np.savetxt('txt_quantized/conv2_weight_32.txt', int_conv2_weight_32, fmt='%1.2x',delimiter = " ")
np.savetxt('txt_quantized/conv2_weight_33.txt', int_conv2_weight_33, fmt='%1.2x',delimiter = " ")

np.savetxt('txt_quantized/conv2_bias.txt', int_conv2_bias, fmt='%1.2x',delimiter = " ")

#################### Weight & Bias in HEX of Fully Connected Layer ####################

print(np.shape(model.fc_1.weight()))
print(model.fc_1.weight().int_repr())

print(np.shape(model.fc_1.bias()))
print(model.fc_1.bias())

int_fc_weight = model.fc_1.weight().int_repr().to(torch.int32)

scale_fc = model.fc_1.scale
scale_fc_input = model.mp2_out_np.max() / 127.0
bias_float_fc = model.fc_1.bias().detach()
int_fc_bias = torch.round(bias_float_fc / (scale_fc_input * scale_fc)).to(torch.int32)

# 2's Complement
for i in range(10):
    for j in range(48):
        if int_fc_weight[i][j] < 0 :
            int_fc_weight[i][j] += 256
    if int_fc_bias[i] < 0 :
        int_fc_bias[i] += 256
        
print(int_fc_weight)
print(int_fc_bias)

np.savetxt('txt_quantized/fc_weight.txt', int_fc_weight, fmt='%1.2x',delimiter = " ")
np.savetxt('txt_quantized/fc_bias.txt', int_fc_bias, fmt='%1.2x',delimiter = " ")

#################### Output Data of each layer ####################
print(np.shape(model.conv1_out_np))
np.savetxt('txt_quantized/out_conv1_value_1.txt', model.conv1_out_np[0][0], fmt='%1.5d',delimiter = " ")
np.savetxt('txt_quantized/out_conv1_value_2.txt', model.conv1_out_np[0][1], fmt='%1.5d',delimiter = " ")
np.savetxt('txt_quantized/out_conv1_value_3.txt', model.conv1_out_np[0][2], fmt='%1.5d',delimiter = " ")

print(np.shape(model.mp1_out_np))
np.savetxt('txt_quantized/out_mp1_value_1.txt', model.mp1_out_np[0][0], fmt='%1.5d',delimiter = " ")
np.savetxt('txt_quantized/out_mp1_value_2.txt', model.mp1_out_np[0][1], fmt='%1.5d',delimiter = " ")
np.savetxt('txt_quantized/out_mp1_value_3.txt', model.mp1_out_np[0][2], fmt='%1.5d',delimiter = " ")

print(np.shape(model.conv2_out_np))
np.savetxt('txt_quantized/out_conv2_value_1.txt', model.conv2_out_np[0][0], fmt='%1.5d',delimiter = " ")
np.savetxt('txt_quantized/out_conv2_value_2.txt', model.conv2_out_np[0][1], fmt='%1.5d',delimiter = " ")
np.savetxt('txt_quantized/out_conv2_value_3.txt', model.conv2_out_np[0][2], fmt='%1.5d',delimiter = " ")

print(np.shape(model.mp2_out_np))
np.savetxt('txt_quantized/out_mp2_value_1.txt', model.mp2_out_np[0][0], fmt='%1.5d',delimiter = " ")
np.savetxt('txt_quantized/out_mp2_value_2.txt', model.mp2_out_np[0][1], fmt='%1.5d',delimiter = " ")
np.savetxt('txt_quantized/out_mp2_value_3.txt', model.mp2_out_np[0][2], fmt='%1.5d',delimiter = " ")

print(np.shape(model.fc_in_np))
np.savetxt('txt_quantized/fc_in_value.txt', model.fc_in_np, fmt='%1.5d',delimiter = " ")

print(np.shape(model.fc_out_np))
np.savetxt('txt_quantized/fc_out_value.txt', model.fc_out_np, fmt='%1.5d',delimiter = " ")


np.set_printoptions(suppress=True)
np.set_printoptions(precision=6)

print("Original Input")
print(model.mp1_out_np[0])
orig_input_1 = model.mp1_out_np[0][0]
orig_input_2 = model.mp1_out_np[0][1]
orig_input_3 = model.mp1_out_np[0][2]

print("Original Weight")
print(model.conv2.weight().int_repr().numpy())
orig_weight = model.conv2.weight().int_repr().numpy()

print("Original Bias")
print(model.conv2.bias().detach().numpy())
orig_bias = model.conv2.bias().detach().numpy()

orig_output_calc_1 = np.zeros((3,8,8))
orig_output_calc_2 = np.zeros((3,8,8))
orig_output_calc_3 = np.zeros((3,8,8))
orig_output_calc = np.zeros((3,8,8))

for c in range(3):
    for i in range(8):
        for j in range(8):
            # MAC
            orig_output_calc_1[c][i][j] += (orig_input_1[i:i+5, j:j+5] * orig_weight[c][0]).sum()
            orig_output_calc_2[c][i][j] += (orig_input_2[i:i+5, j:j+5] * orig_weight[c][1]).sum()
            orig_output_calc_3[c][i][j] += (orig_input_3[i:i+5, j:j+5] * orig_weight[c][2]).sum()         
            orig_output_calc[c][i][j] = orig_output_calc_1[c][i][j] + orig_output_calc_2[c][i][j] + orig_output_calc_3[c][i][j] + orig_bias[c]
        
print("\nBias : ")
print(orig_bias)
print("\nCalc Value :\n")
print(orig_output_calc) 
print("\nReal Value :\n")
print(model.conv2_out_np[0])

np.set_printoptions(precision=0)

print("Convolution Input")
print(np.shape(model.mp1_out_np))
_input = model.mp1_out_np[0] * 128
print(_input)
print('\n')

print("Convolution Weight")
print(np.shape(model.conv2.weight().int_repr().numpy()))
weight = model.conv2.weight().int_repr().to(torch.int32).numpy() * 128
print(weight)

print("Convolution Bias")
print(np.shape(model.conv2.bias().detach().numpy()))
bias = model.conv2.bias().detach().numpy() * 128
print(bias)

print("Convolution Output")
print(np.shape(model.conv2_out_np))
output = model.conv2_out_np * 128
print(output)

print(np.shape(_input))
print(np.shape(weight))
print(np.shape(output))

_input_1 = _input[0]
_input_2 = _input[1]
_input_3 = _input[2]

output_calc_1 = np.zeros((3,8,8))
output_calc_2 = np.zeros((3,8,8))
output_calc_3 = np.zeros((3,8,8))
output_calc = np.zeros((3,8,8))

for c in range(3):
    for i in range(8):
        for j in range(8):
            # MAC
            output_calc_1[c][i][j] += (_input_1[i:i+5, j:j+5] * weight[c][0]).sum()
            output_calc_2[c][i][j] += (_input_2[i:i+5, j:j+5] * weight[c][1]).sum()
            output_calc_3[c][i][j] += (_input_3[i:i+5, j:j+5] * weight[c][2]).sum()
            output_calc[c][i][j] = output_calc_1[c][i][j] + output_calc_2[c][i][j] + output_calc_3[c][i][j] + bias[c]
        
print("\nBias : ")
print(bias)
print("\nCalc Value :\n")
print(output_calc / 128) 
print("\nReal Value :\n")
print(output)

np.set_printoptions(precision=0)
print("\nCalc Value 1 :\n")
print(output_calc_1) 

print("\nCalc Value 2 :\n")
print(output_calc_2) 

print("\nCalc Value 3 :\n")
print(output_calc_3) 

print("Sum")
print(output_calc_1 + output_calc_2 + output_calc_3)
