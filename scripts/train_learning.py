"""Train versioned local learning artifacts on D: using the current real-data snapshot."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from finsocratic.storage import WorkspaceStore
from finsocratic.learning import train, status

if __name__ == '__main__':
    train(WorkspaceStore())
    report = status()['report']
    print({key: report[key] for key in ('run_id', 'training_samples', 'independent_name_groups', 'validation', 'test', 'neural_passed_baselines')})
