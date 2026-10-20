"""Research evaluation CLI. Every run writes a reproducible record to data/experiments/.

    python -m chesscoach.evaluation annotation-template config/experiments/pilot.yaml
    python -m chesscoach.evaluation benchmark          config/experiments/pilot.yaml --gold gold.csv
    python -m chesscoach.evaluation review-precision   config/experiments/pilot.yaml
    python -m chesscoach.evaluation predictive         config/experiments/pilot.yaml
    python -m chesscoach.evaluation coaching-package   config/experiments/pilot.yaml
    python -m chesscoach.evaluation coaching-score     config/experiments/pilot.yaml \\
        --ratings ratings.csv --key KEY_do_not_share_with_raters.json
"""

import argparse
import json
from pathlib import Path

from chesscoach.db.session import get_sessionmaker
from chesscoach.evaluation import benchmark, comparison, predictive
from chesscoach.evaluation.experiment import ExperimentConfig, record, results_dir


def run(command: str, config: ExperimentConfig, args) -> Path:
    work = results_dir() / config.name
    with get_sessionmaker()() as db:
        if command == "annotation-template":
            info = benchmark.annotation_template(db, config, work / "annotation_template.csv")
            results, dataset = (
                {k: v for k, v in info.items() if k != "game_ids"},
                {"game_ids": info["game_ids"]},
            )
        elif command == "benchmark":
            results, dataset = benchmark.score_benchmark(db, Path(args.gold))
        elif command == "review-precision":
            results, dataset = benchmark.review_precision(db, config)
        elif command == "predictive":
            results, dataset = predictive.predictive_validity(db, config)
        elif command == "coaching-package":
            results, dataset = comparison.coaching_package(db, config, work / "coaching")
        elif command == "coaching-score":
            results, dataset = comparison.score_ratings(Path(args.ratings), Path(args.key))
        else:  # pragma: no cover - argparse restricts choices
            raise ValueError(command)
    return record(command, config, dataset, results)


def main() -> None:
    parser = argparse.ArgumentParser(description="ChessMentor AI research evaluation")
    parser.add_argument(
        "command",
        choices=[
            "annotation-template",
            "benchmark",
            "review-precision",
            "predictive",
            "coaching-package",
            "coaching-score",
        ],
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--gold", help="Filled-in annotation CSV (benchmark)")
    parser.add_argument("--ratings", help="Filled-in ratings CSV (coaching-score)")
    parser.add_argument("--key", help="Key file from coaching-package (coaching-score)")
    args = parser.parse_args()
    path = run(args.command, ExperimentConfig.load(args.config), args)
    print(json.dumps(json.loads(path.read_text(encoding="utf-8"))["results"], indent=2)[:4000])
    print(f"\nFull record: {path}")


if __name__ == "__main__":
    main()
