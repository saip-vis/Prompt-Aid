# Retrieval evaluation

This is a small, hand-authored synthetic test, not a production benchmark. Two fictional projects contain five source files each. `queries.json` contains 17 manually labeled requests: 16 with one relevant source file and one deliberately unrelated query. Four use less literal wording to expose lexical limitations. The fixture text and expected labels were written together, so the results can be optimistic and do not establish real-world performance.

Metrics use unique file paths after ranking chunks: recall@1 and recall@3 measure the fraction of positive requests with their labeled file in the first 1 or 3; MRR averages reciprocal rank of the first labeled file; abstention checks whether an unrelated query returned no results. One unrelated query is far too little to estimate a false-positive rate.

Reproduce after installing optional vector and ML dependencies:

```sh
.venv/bin/python evaluation/evaluate.py --method bm25
.venv/bin/python evaluation/evaluate.py --method qdrant
.venv/bin/python evaluation/train_torch.py --train-project cedar --test-project harbor
.venv/bin/python evaluation/train_torch.py --train-project harbor --test-project cedar
```

The Qdrant experiment uses an **in-memory** collection and corpus-fitted TF-IDF vectors, so it is still lexical; it does not download a pretrained semantic model. The PyTorch experiment trains a tiny pairwise reranker on BM25 candidates from one project and evaluates the other. It cannot retrieve a relevant file that BM25 omitted. No personal repository is indexed or used to train it.

The checked-in `results/` files are the reports from the development run. On this tiny set BM25 and Qdrant each achieved 13/16 recall@1 and 13/16 recall@3, with one abstention on the single unrelated query. Training on Cedar produced only four pairs, and the held-out Harbor reranker tied BM25 at 7/8 recall@1. Training on Harbor produced three pairs, and the held-out Cedar reranker tied BM25 at 6/8 recall@1. These results do not justify switching the default retriever to Qdrant or PyTorch. Larger, independently labeled real-world cases and a semantic model are needed before considering a learned retriever.

## Persistent semantic comparison

`benchmark.py` compares the new persistent BM25, semantic, hybrid, and optional
pretrained CrossEncoder reranker on the same labeled queries. It reports actual
file recall@1/@3, MRR, no-match abstention, and per-query timings. You can provide
an independently labeled corpus with `--cases` and `--fixtures`; each case has
`id`, `project`, `query`, and `relevant` file paths. Keep tuning and training data
separate from the test repositories.

```sh
HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
.venv/bin/python evaluation/benchmark.py \
  --embedding-model /local/embedding-model \
  --reranker-model /local/reranker-model \
  --output evaluation/results/persistent-comparison.json
```

The development run used all-MiniLM-L6-v2 embeddings and the
ms-marco-MiniLM-L6-v2 CrossEncoder, both pretrained general-text baselines on CPU.
The checked-in persistent comparison recorded BM25 at **13/16** first-file hits
and semantic/hybrid at **14/16**. Reranking stayed at **14/16**, so no additional
reranking benefit was demonstrated. BM25 remains the default. No training or
fine-tuning was performed. All methods abstained on the single unrelated query,
which cannot establish a reliable false-positive rate. Small synthetic fixtures
and one extra hit do not demonstrate real-world improvement.

## Rewrite quality and task outcomes

`rewrite_eval.py` aggregates **human-labeled** paired reviews. It does not infer
semantic correctness from keyword matching or fabricate labels for ungraded
reviews. Export saved reviews through `GET /reviews/{id}` and prepare a JSON array:

```json
[
  {
    "id": "held-out-example-1",
    "original": "Original request",
    "improved": "Actual reviewed rewrite",
    "judgments": null
  }
]
```

Evaluate each pair without knowing which configuration produced it. Replace
`judgments` with these independently assessed fields when labeling is complete:

- `intent_preserved`: boolean;
- `constraints_preserved`: boolean;
- `unsupported_requirements`: non-negative count;
- `task_success_original` and `task_success_improved`: optional boolean task
  results from comparable disposable checkouts using the same model, tools,
  execution budgets and task tests. Omit results that were not actually run.

```sh
.venv/bin/python evaluation/rewrite_eval.py /private/path/labeled-reviews.json
```

The report separates ungraded cases and paired task outcomes; missing grades are
never counted as successes. Record evaluator identities, disagreements and task
rubrics alongside your private corpus. There is not yet a real-world rewrite
quality dataset or evidence that Prompt Aid increases coding task success.
