.PHONY: install fetch run-mock run-claude run-openai score post clean

install:
	pip install -e ".[claude,openai,plot]"

fetch:
	python -m triage_eval.fetch --repo grafana/grafana --n 500
	python -m triage_eval.fetch --repo prometheus/prometheus --n 500

run-mock:
	python -m triage_eval.run --provider mock

run-claude:
	python -m triage_eval.run --provider claude --model claude-sonnet-4-6

run-openai:
	python -m triage_eval.run --provider openai --model gpt-4o

score:
	python -m triage_eval.score --compare

post:
	python scripts/make_post.py --chart

clean:
	rm -f data/*.jsonl results/*.jsonl results/*.json results/post.md results/comparison.png

serve:
	python scripts/serve.py
