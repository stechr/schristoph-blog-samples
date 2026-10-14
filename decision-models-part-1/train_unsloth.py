"""Fine-tune a decision model with Unsloth, calibrate it, and write predictions.

Needs an NVIDIA GPU (CUDA capability 7.0 or newer). On GPUs without bfloat16,
such as the T4, Unsloth trains Qwen3.5 in float32, which is much slower.

The training calls follow Unsloth's published decision-model notebook and guide.
The script adds three things: it can read your own JSONL rows, it writes
predictions for evaluate.py, and it saves the model to a local folder you can
upload to S3 for serving.

    python train_unsloth.py --dataset typed-decisions --out-dir run-td
    python train_unsloth.py --dataset routing-train.jsonl --test routing-test.jsonl --out-dir run-routing
"""
import argparse
import json
import os


def load_rows(source, split):
    from datasets import Dataset, load_dataset

    if source == "typed-decisions":
        return load_dataset("LocalLLaMA/typed-decisions", "all", split=split)
    with open(source) as fh:
        return Dataset.from_list([json.loads(line) for line in fh if line.strip()])


def write_predictions(model, tokenizer, rows, path):
    from unsloth import FastDecisionModel

    FastDecisionModel.for_inference(model)
    with open(path, "w") as fh:
        for row in rows:
            questions = json.loads(row["questions"])
            answers = FastDecisionModel.predict(model, tokenizer, row["state"], questions)
            out = {
                name: {"probabilities": {str(k).lower(): float(v) for k, v in res["probabilities"].items()}}
                for name, res in answers.items()
            }
            fh.write(json.dumps({"id": row["id"], "answers": out}) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", default="typed-decisions", help="'typed-decisions' or a train JSONL")
    ap.add_argument("--test", default=None, help="test JSONL (default: the dataset's test split)")
    ap.add_argument("--model", default="unsloth/Qwen3.5-4B")
    ap.add_argument("--max-steps", type=int, default=60, help="60 = Unsloth's quick run")
    ap.add_argument("--out-dir", default="run")
    ap.add_argument("--model-dir", default=None, help="where to save the model (default: out-dir)")
    ap.add_argument("--gguf", action="store_true", help="also try a q8_0 GGUF export for llama.cpp")
    args = ap.parse_args()
    model_dir = args.model_dir or args.out_dir
    metrics = {}

    from transformers import TrainingArguments
    from unsloth import DecisionTrainer, FastDecisionModel, is_bfloat16_supported

    model, tokenizer = FastDecisionModel.from_pretrained(
        model_name=args.model, max_seq_length=2048, load_in_4bit=True
    )
    model = FastDecisionModel.get_peft_model(
        model, r=16, lora_alpha=16, lora_dropout=0,
        use_gradient_checkpointing="unsloth", random_state=3407,
    )

    items, report = FastDecisionModel.build_dataset(load_rows(args.dataset, "train"), tokenizer, model)
    print(f"Skipped {report['skipped']} of {report['total']} decisions")
    train_items, eval_items = FastDecisionModel.split_holdout(items, seed=3407)
    metrics["build_report"] = {k: report[k] for k in ("skipped", "total") if k in report}
    metrics["before_training_holdout"] = FastDecisionModel.evaluate(model, tokenizer, eval_items)
    print("before training:", metrics["before_training_holdout"])

    trainer = DecisionTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=train_items,
        eval_dataset=eval_items,
        args=TrainingArguments(
            per_device_train_batch_size=8,
            gradient_accumulation_steps=4,
            warmup_steps=10,
            max_steps=args.max_steps,
            learning_rate=2e-4,
            lr_scheduler_type="cosine",
            weight_decay=0.01,
            bf16=is_bfloat16_supported(),
            fp16=not is_bfloat16_supported(),
            eval_strategy="epoch",
            logging_steps=10,
            output_dir=os.path.join(args.out_dir, "checkpoints"),
            report_to="none",
            seed=3407,
        ),
    )
    train_out = trainer.train()
    metrics["train"] = {"runtime_s": train_out.metrics.get("train_runtime"), "loss": train_out.training_loss}

    # Calibrate on the held-out rows, then measure on rows the model never saw.
    metrics["after_training_holdout"] = FastDecisionModel.evaluate(model, tokenizer, eval_items)
    print("after training:", metrics["after_training_holdout"])
    metrics["calibration"] = FastDecisionModel.calibrate(model, tokenizer, eval_items)
    print("calibration:", metrics["calibration"])
    # Save first, so a failure in the measurements below never loses the trained model.
    os.makedirs(model_dir, exist_ok=True)
    model.save_pretrained(os.path.join(model_dir, "adapter"))  # LoRA + head + calibration
    tokenizer.save_pretrained(os.path.join(model_dir, "adapter"))
    model.save_pretrained_merged(os.path.join(model_dir, "merged"), tokenizer, save_method="merged_16bit")

    os.makedirs(args.out_dir, exist_ok=True)
    test_rows = load_rows(args.test, "train") if args.test else load_rows("typed-decisions", "test")
    try:
        test_items, _ = FastDecisionModel.build_dataset(test_rows, tokenizer, model)
        metrics["test"] = FastDecisionModel.evaluate(model, tokenizer, test_items)
        print("test:", metrics["test"])
    finally:
        with open(os.path.join(args.out_dir, "metrics.json"), "w") as fh:
            json.dump(metrics, fh, indent=2, default=str)
    write_predictions(model, tokenizer, test_rows, os.path.join(args.out_dir, "predictions.jsonl"))

    if args.gguf:  # llama.cpp format for serving; needs llama.cpp tooling, so failure is not fatal
        try:
            model.save_pretrained_gguf(os.path.join(model_dir, "gguf"), tokenizer, quantization_method="q8_0")
        except Exception as exc:  # noqa: BLE001
            print("GGUF export skipped:", repr(exc))

if __name__ == "__main__":
    main()
