import os
import sys
import torch
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

# Tenta importar unsloth (pode não estar instalado no ambiente padrão)
try:
    from unsloth import FastLanguageModel
except ImportError:
    print("❌ Erro: Biblioteca 'unsloth' não encontrada.")
    print("Instale com: pip install \"unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git\"")
    print("Nota: Requer GPU NVIDIA.")
    sys.exit(1)

def train(dataset_path: str = "dataset_qlora.jsonl", output_dir: str = "outputs"):
    print(f"🚀 Iniciando treino QLoRA com dataset: {dataset_path}")
    
    # 1. Configuração
    max_seq_length = 4096
    dtype = None # Auto detecção
    load_in_4bit = True

    # 2. Carregar Modelo Base
    # Usando sqlcoder-7b-2 como base
    model_name = "defog/sqlcoder-7b-2"
    print(f"📥 Carregando modelo base: {model_name}")
    
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = model_name,
        max_seq_length = max_seq_length,
        dtype = dtype,
        load_in_4bit = load_in_4bit,
    )

    # 3. Adicionar Adaptadores LoRA
    print("🔧 Configurando LoRA (Rank=16)...")
    model = FastLanguageModel.get_peft_model(
        model,
        r = 16,
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                          "gate_proj", "up_proj", "down_proj",],
        lora_alpha = 16,
        lora_dropout = 0,
        bias = "none",
        use_gradient_checkpointing = "unsloth",
        random_state = 3407,
    )

    # 4. Preparar Dataset
    dataset = load_dataset("json", data_files=dataset_path, split="train")
    
    alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{}

### Input:
{}

### Response:
{}"""

    EOS_TOKEN = tokenizer.eos_token 
    def formatting_prompts_func(examples):
        instructions = examples["instruction"]
        inputs       = examples["input"]
        outputs      = examples["output"]
        texts = []
        for instruction, input, output in zip(instructions, inputs, outputs):
            text = alpaca_prompt.format(instruction, input, output) + EOS_TOKEN
            texts.append(text)
        return { "text" : texts, }

    dataset = dataset.map(formatting_prompts_func, batched = True)

    # 5. Treinamento
    print("🏋️ Começando treinamento...")
    trainer = SFTTrainer(
        model = model,
        tokenizer = tokenizer,
        train_dataset = dataset,
        dataset_text_field = "text",
        max_seq_length = max_seq_length,
        dataset_num_proc = 2,
        packing = False,
        args = TrainingArguments(
            per_device_train_batch_size = 2,
            gradient_accumulation_steps = 4,
            warmup_steps = 5,
            max_steps = 60, # Ajustar conforme necessidade (ex: 1 epoch completa)
            learning_rate = 2e-4,
            fp16 = not torch.cuda.is_bf16_supported(),
            bf16 = torch.cuda.is_bf16_supported(),
            logging_steps = 1,
            optim = "adamw_8bit",
            weight_decay = 0.01,
            lr_scheduler_type = "linear",
            seed = 3407,
            output_dir = output_dir,
        ),
    )

    trainer.train()

    # 6. Salvar
    print("💾 Salvando modelo GGUF...")
    key = "q4_k_m"
    model.save_pretrained_gguf("model_qlora_gguf", tokenizer, quantization_method = key)
    print(f"✅ Modelo salvo em model_qlora_gguf/ com quantização {key}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset_qlora.jsonl")
    args = parser.parse_args()
    
    if not os.path.exists(args.dataset):
        print(f"❌ Dataset não encontrado: {args.dataset}")
        sys.exit(1)
        
    train(dataset_path=args.dataset)
