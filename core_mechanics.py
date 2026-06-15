import torch
import torch.nn as nn
import time

class BoomerangLoss(nn.Module):
    def __init__(self, alpha=0.1, beta=0.5, gamma=0.99):
        super(BoomerangLoss, self).__init__()
        self.alpha = alpha  # ضریب هنگ‌اور درونی (Simeks Overload)
        self.beta = beta    # ضریب اثر پروانه‌ای بیرونی (Butterfly Delta)
        self.gamma = gamma  # ضریب تنزیل زمان کیفی (Z-Time Discount)
        self.base_loss = nn.MSELoss()

    def forward(self, y_pred, y_true, network_weights, future_predictions):
        loss_task = self.base_loss(y_pred, y_true)
        loss_hangover = torch.norm(network_weights, p=2) 
        loss_butterfly = 0
        for t, delta_i in enumerate(future_predictions):
            loss_butterfly += (self.gamma ** t) * torch.sum(delta_i ** 2)
            
        total_zurvan_loss = loss_task + (self.alpha * loss_hangover) + (self.beta * loss_butterfly)
        return total_zurvan_loss

def zurvan_halting_protocol(crisis_scenario, z_time_limit):
    start_time = time.time()
    compute_time_allocated = z_time_limit * 0.95
    
    best_action = None
    min_current_friction = float('inf')
    
    while time.time() - start_time < compute_time_allocated:
        simulated_action = crisis_scenario.generate_probabilistic_action()
        future_cost = crisis_scenario.simulate_butterfly_effect(simulated_action)
        
        if future_cost < min_current_friction:
            min_current_friction = future_cost
            best_action = simulated_action
            
        if future_cost == 0:
            return best_action

    print("⚠️ [Halting Point] زمان مجاز رو به پایان است. محاسبات آینده متوقف شد.")
    print("🌀 [Leap of Faith] پروتکل توکل زوروانی فعال شد. منیت تحلیلی ماشین صفر شد.")
    
    immediate_actions = crisis_scenario.get_immediate_options()
    best_action = min(immediate_actions, key=lambda a: crisis_scenario.evaluate_immediate_compassion(a))
    
    return best_action
