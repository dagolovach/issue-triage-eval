.PHONY: install fetch run-mock run-claude run-openai score clean serve

install:
	pip install -e ".[claude,openai,plot]"

fetch:
	python -m triage_eval.fetch --repo grafana/grafana --n 500 --workers 10
	python -m triage_eval.fetch --repo prometheus/prometheus --n 500 --workers 10
	python -m triage_eval.fetch --repo cli/cli --n 500 --workers 10

run-mock:
	python -m triage_eval.run --provider mock

run-claude:
	python -m triage_eval.run --provider claude --model claude-sonnet-4-6 --workers 10

run-openai:
	python -m triage_eval.run --provider openai --model gpt-4o --workers 10

score:
	python -m triage_eval.score --compare

clean:
	rm -f data/*.jsonl results/*.jsonl results/*.json results/comparison.png results/*

serve:
	python scripts/serve.py
