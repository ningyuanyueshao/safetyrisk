import os
from transformers import AutoImageProcessor, ResNetForImageClassification
import torch

# Hugging Face 上的图像模型 ID
model_id = "microsoft/resnet-50"
# 你期望保存的本地目录路径
local_save_dir = "./resnet50"

print(f"正在从 Hugging Face 下载模型和图像处理器: {model_id} ...")

try:
    # 1. 下载并加载图像处理器 (Image Processor)
    # 负责图片的 Resize, Normalization 等预处理
    image_processor = AutoImageProcessor.from_pretrained(model_id)

    # 2. 下载并加载模型本体。
    # ⚠️ 关键点：我们指定 num_labels=3，并开启 ignore_mismatched_sizes=True。
    # 这会自动抛弃原版的 1000 分类层，替换为一个未经训练的 3 分类线性层，
    # 从而完美对齐你的 L2 图像决策需求。
    model = ResNetForImageClassification.from_pretrained(
        model_id, 
        num_labels=3, 
        ignore_mismatched_sizes=True
    )

    print("下载完成，正在保存到本地目录...")

    # 3. 将完整结构（模型权重、配置文件、图像处理器配置）保存到本地
    image_processor.save_pretrained(local_save_dir)
    model.save_pretrained(local_save_dir)

    print(f"✅ 图像分类模型已成功保存至本地目录：{local_save_dir}")

except Exception as e:
    print(f"❌ 发生错误: {e}")