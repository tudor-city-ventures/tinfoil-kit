"""Make a tiny random-weight llama GGUF (gibberish output) to test the kit's plumbing."""
import sys

import gguf  # pip install gguf
import numpy as np

# usage: make_tiny_model.py OUT.gguf [SEED]   (a different seed simulates a re-uploaded model)
out = sys.argv[1]
n_vocab, n_embd, n_layer, n_head, n_ff = 259, 64, 2, 4, 128
rng = np.random.default_rng(int(sys.argv[2]) if len(sys.argv) > 2 else 0)

w = gguf.GGUFWriter(out, "llama")
w.add_name("tiny-test")
w.add_context_length(4096)
w.add_embedding_length(n_embd)
w.add_block_count(n_layer)
w.add_feed_forward_length(n_ff)
w.add_head_count(n_head)
w.add_head_count_kv(n_head)
w.add_layer_norm_rms_eps(1e-5)
w.add_rope_dimension_count(n_embd // n_head)
w.add_file_type(0)

tokens = [b"<unk>", b"<s>", b"</s>"] + [f"<0x{i:02X}>".encode() for i in range(256)]
w.add_tokenizer_model("llama")
w.add_token_list(tokens)
w.add_token_scores([0.0] * len(tokens))
w.add_token_types([2, 3, 3] + [6] * 256)
w.add_unk_token_id(0)
w.add_bos_token_id(1)
w.add_eos_token_id(2)
w.add_chat_template(
    "{% for m in messages %}{{ m['role'] }}: {{ m['content'] }}\n{% endfor %}"
    "{% if add_generation_prompt %}assistant:{% endif %}")


def t(name, *shape):
    w.add_tensor(name, (rng.standard_normal(shape) * 0.02).astype(np.float32))


t("token_embd.weight", n_vocab, n_embd)
w.add_tensor("output_norm.weight", np.ones(n_embd, dtype=np.float32))
t("output.weight", n_vocab, n_embd)
for i in range(n_layer):
    w.add_tensor(f"blk.{i}.attn_norm.weight", np.ones(n_embd, dtype=np.float32))
    t(f"blk.{i}.attn_q.weight", n_embd, n_embd)
    t(f"blk.{i}.attn_k.weight", n_embd, n_embd)
    t(f"blk.{i}.attn_v.weight", n_embd, n_embd)
    t(f"blk.{i}.attn_output.weight", n_embd, n_embd)
    w.add_tensor(f"blk.{i}.ffn_norm.weight", np.ones(n_embd, dtype=np.float32))
    t(f"blk.{i}.ffn_gate.weight", n_ff, n_embd)
    t(f"blk.{i}.ffn_up.weight", n_ff, n_embd)
    t(f"blk.{i}.ffn_down.weight", n_embd, n_ff)

w.write_header_to_file()
w.write_kv_data_to_file()
w.write_tensors_to_file()
w.close()
print("wrote", out)
