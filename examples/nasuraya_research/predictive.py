"""PredVLA sensory inference on native fixture observations, without actuation."""
from copy import deepcopy
import math

from .adapters import digest, FEATURES
from .integrity import verify_sources


def config():
    return {'model': dict(v_dim=6, q_dim=6, a_dim=1, l_dim=2, r=4,
        d=16, d_top=8, pb_dim=4, head_hidden=16, gmm_k=1, gmm_min_std=.01,
        tau_top=4., tau_v=2., tau_up=2., tau_low=1.,
        w_top=.001, w_v=.001, w_up=.001, w_low=.001)}


def weight_state(model):
    return {k: t.detach().cpu().tolist() for k, t in model.state_dict().items()}


def restore_observer(saved):
    """Restore finite JSON tensors only; never deserialize an executable pickle."""
    verify_sources()
    import torch
    from .vendor.predvla.model import PredVLA
    if (not isinstance(saved, dict) or set(saved) != {'config', 'state', 'training'} or
            saved['config'] != config() or
            digest(saved['state']) != saved['training']['weight_sha256']):
        raise ValueError('sensory weights/config integrity')
    model = PredVLA(config())
    expected = model.state_dict()
    if set(saved['state']) != set(expected):
        raise ValueError('sensory weight keys')
    tensors = {k: torch.tensor(v, dtype=expected[k].dtype) for k, v in saved['state'].items()}
    if any(t.shape != expected[k].shape or not torch.isfinite(t).all() for k, t in tensors.items()):
        raise ValueError('sensory weight shape/nonfinite')
    model.load_state_dict(tensors, strict=True)
    return model.eval().requires_grad_(False)


def train_observer(train_sequences, *, seed, steps=64):
    """Train only sensory predictions on explicitly supplied training sequences.

    Action head has zero loss weight and is NEVER an actuator. This small
    adaptation has no language encoder, LIBERO weights, camera or robot data.
    """
    verify_sources()
    import torch
    from .vendor.predvla.model import PredVLA
    if type(seed) is not int or type(steps) is not int or not 1 <= steps <= 64:
        raise ValueError('bounded seed/training steps')
    v, q = tensors(train_sequences)
    torch.manual_seed(seed)
    model = PredVLA(config())
    l = torch.tensor([[1., 0.]]).expand(len(train_sequences), -1)
    a = torch.zeros(q.shape[0], q.shape[1], 1)
    mask = torch.ones(q.shape[:2])
    optimizer = torch.optim.Adam(model.parameters(), lr=.01)
    losses = []
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = model.free_energy(None, l, v, q, a, mask, mask,
                                 lambda_a=0., use_prior=True)['total']
        if not torch.isfinite(loss):
            raise ValueError('nonfinite training loss')
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach()))
    model.eval().requires_grad_(False)
    return model, dict(seed=seed, steps=steps, loss_before=losses[0],
                      loss_last=losses[-1], weight_sha256=digest(weight_state(model)),
                      features=list(FEATURES), action_loss_weight=0.,
                      scope='native synthetic sensory observer adaptation, not original PredVLA model')


def tensors(sequences):
    import torch
    if (not isinstance(sequences, list) or not 1 <= len(sequences) <= 8 or
            any(not isinstance(s, list) or not 1 <= len(s) <= 4 for s in sequences) or
            len({len(s) for s in sequences}) != 1):
        raise ValueError('bounded equal-length sensory sequences')
    for sequence in sequences:
        for sample in sequence:
            for name in ('q', 'v'):
                x = sample[name]
                if (not isinstance(x, list) or len(x) != 6 or
                        not all(type(v) in (int, float) and math.isfinite(v) for v in x)):
                    raise ValueError('finite six-dimensional sensory features')
    return (torch.tensor([[x['v'] for x in s] for s in sequences], dtype=torch.float32),
            torch.tensor([[x['q'] for x in s] for s in sequences], dtype=torch.float32))


def infer_observer(model, sequence, *, iterations=10):
    """Correct latent states with CURRENT/past senses, never with future labels.

    Return reconstruction errors only. The untrained action vector returned
    by upstream ERRollout.step() is deliberately discarded in this function.
    """
    verify_sources()
    import torch
    from .vendor.predvla.er import ERRollout
    if type(iterations) is not int or not 0 <= iterations <= 10:
        raise ValueError('bounded inference iterations')
    v, q = tensors([sequence])
    model = deepcopy(model).eval().requires_grad_(False)
    before = digest(weight_state(model))
    roller = ERRollout(model, torch.tensor([1., 0.]), window=4,
                       n_itr=iterations, lr=.05, device='cpu', vision_stride=1)
    errors = []
    for i in range(len(sequence)):
        _unused_action = roller.step(v[0, i], q[0, i])
        if not all(math.isfinite(x) for x in (roller.last_eps_q, roller.last_eps_v)):
            raise ValueError('nonfinite inference')
        errors.append(dict(q_mse=roller.last_eps_q, geometry_mse=roller.last_eps_v))
    if digest(weight_state(model)) != before:
        raise ValueError('inference changed trained weights')
    return dict(errors=errors, mean_q_mse=sum(x['q_mse'] for x in errors)/len(errors),
                mean_geometry_mse=sum(x['geometry_mse'] for x in errors)/len(errors),
                weights_unchanged=True, native_actions_executed=0,
                upstream_action_output_used=False, iterations=iterations,
                scope='current sensory reconstruction; not future forecasting or policy success')
