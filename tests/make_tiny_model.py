"""Make a tiny llama GGUF for tests. Whatever it's asked, it writes ANSWER, so tests can check that an AI's answer
reaches the page with every character intact (a model with random weights writes random bytes, which look like a
broken page).

Its layers add nothing (their output weights are zero), so each next token depends only on the last one, and the
embeddings and output weights chain the prompt's last token through ANSWER to the end token. The other weights are
random, by SEED, so another seed makes another file with the same answer (a re-uploaded model).

usage: make_tiny_model.py OUT.gguf [SEED]"""
import sys

# ANSWER token by token, "|" between them. A token can't repeat: each has exactly one next token. é, ½ and — are
# spelled byte by byte, as real models write a character they have no token for, so a decoder that mangles a character
# split between tokens or network reads shows it.
TOKENS = ("**This| is| the| kit's| test| AI.**| It| gives| one| fixed| answer| to| any| question,| so| tests| can|"
          " check| that| each| character| arrives| intact| [1].| Accents| and| symbols| too:| caf|é|, |½| cup, 20 °C |—|"
          " all there.").split("|")
ANSWER = "".join(TOKENS)
SPELLED = "é½—"


def main(out, seed):
    import gguf  # pip install gguf
    import numpy as np

    vocab = [b"<unk>", b"<s>", b"</s>"] + [f"<0x{i:02X}>".encode() for i in range(256)]
    types = [2, 3, 3] + [6] * 256
    eos, byte = 2, (lambda b: 3 + b)
    chain = []
    for t in TOKENS:
        if t in SPELLED:
            chain += [byte(b) for b in t.encode()]
        else:
            chain.append(len(vocab))
            vocab.append(t.replace(" ", "▁").encode())
            types.append(1)
    starts = [byte(ord(":")), byte(ord("\n"))]   # the prompt ends "assistant:", or "\n" in a server's own template
    n_vocab, n_embd, n_layer, n_head, n_ff = len(vocab), 64, 2, 4, 128
    assert len(set(chain)) == len(chain) and not set(starts) & set(chain) and len(chain) + 2 <= n_embd

    # Token -> one-hot state: 0 the prompt's end, i the answer's token i, the last one every other token. RMS norm
    # makes a one-hot 8 (the square root of n_embd), so each state's next token gets a logit of 40 and the rest 0:
    # the same answer at any temperature.
    rest = len(chain) + 1
    emb = np.zeros((n_vocab, n_embd), np.float32)
    emb[:, rest] = 1
    emb[starts] = np.eye(n_embd, dtype=np.float32)[0]
    for state, tok in enumerate(chain, 1):
        emb[tok] = np.eye(n_embd, dtype=np.float32)[state]
    out_w = np.zeros((n_vocab, n_embd), np.float32)
    for state, nxt in enumerate(chain + [eos]):
        out_w[nxt, state] = 5
    out_w[eos, rest] = 5

    rng = np.random.default_rng(seed)
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
    w.add_tokenizer_model("llama")
    w.add_token_list(vocab)
    w.add_token_scores([0.0] * n_vocab)
    w.add_token_types(types)
    w.add_unk_token_id(0)
    w.add_bos_token_id(1)
    w.add_eos_token_id(eos)
    w.add_chat_template(
        "{% for m in messages %}{{ m['role'] }}: {{ m['content'] }}\n{% endfor %}"
        "{% if add_generation_prompt %}assistant:{% endif %}")

    ones, zeros = (lambda *s: np.ones(s, np.float32)), (lambda *s: np.zeros(s, np.float32))
    rand = lambda *s: (rng.standard_normal(s) * 0.02).astype(np.float32)   # noqa: E731
    w.add_tensor("token_embd.weight", emb)
    w.add_tensor("output_norm.weight", ones(n_embd))
    w.add_tensor("output.weight", out_w)
    for i in range(n_layer):
        w.add_tensor(f"blk.{i}.attn_norm.weight", ones(n_embd))
        w.add_tensor(f"blk.{i}.attn_q.weight", rand(n_embd, n_embd))
        w.add_tensor(f"blk.{i}.attn_k.weight", rand(n_embd, n_embd))
        w.add_tensor(f"blk.{i}.attn_v.weight", rand(n_embd, n_embd))
        w.add_tensor(f"blk.{i}.attn_output.weight", zeros(n_embd, n_embd))
        w.add_tensor(f"blk.{i}.ffn_norm.weight", ones(n_embd))
        w.add_tensor(f"blk.{i}.ffn_gate.weight", rand(n_ff, n_embd))
        w.add_tensor(f"blk.{i}.ffn_up.weight", rand(n_ff, n_embd))
        w.add_tensor(f"blk.{i}.ffn_down.weight", zeros(n_embd, n_ff))
    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0)
