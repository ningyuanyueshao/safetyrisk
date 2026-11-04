from transformers import AutoModelForSequenceClassification, AutoTokenizer

# Hugging Face 上的模型 ID
model_id = "hfl/chinese-roberta-wwm-ext"
# 你期望保存的本地目录路径
local_save_dir = "./chinese-roberta-wwm-ext"

print("正在从 Hugging Face 下载模型和分词器...")

# 1. 下载并加载分词器 (Tokenizer)
tokenizer = AutoTokenizer.from_pretrained(model_id)

# 2. 下载并加载模型。
# ⚠️ 关键点：我们使用 AutoModelForSequenceClassification 并指定 num_labels=3
# 这会自动在预训练模型顶部添加一个未经训练的 3 分类线性层，完美对齐你的 L2 决策需求。
model = AutoModelForSequenceClassification.from_pretrained(model_id, num_labels=3)

print("下载完成，正在保存到本地目录...")

# 3. 将完整结构（模型权重、配置文件、分词器词表）保存到本地
tokenizer.save_pretrained(local_save_dir)
model.save_pretrained(local_save_dir)

print(f"✅ 模型已成功保存至本地目录：{local_save_dir}")