# Frozen first weight-training run

52 fixed AdamW steps changed 61,440 values in 16 real pretrained-transformer
LoRA tensors and all eight effective target attention matrices. The base model
parameter fingerprints stayed identical. Saved safe-tensor payloads were
independently compared; restoration in a new process reproduced exact effective
weights and answer likelihoods with zero network, optimizer or body steps.

Held-out accuracy stayed 16/24 and balanced accuracy stayed 0.5. Every final
prediction was DEFER, missing all eight admissible requests. Two-choice Brier
improved from 0.215494 to 0.174455 and answer-token NLL decreased, but these do
not establish improved action selection. The fixed run was retained without
held-out-based retraining and the adapter was not deployed to the body/API gate.

The full dataset/receipt stores and adapter binaries are private runtime
checkpoints. Public files contain digests, reduced per-case results, training
example IDs, frozen settings, tests and a 72-file unchanged-native-source audit.
