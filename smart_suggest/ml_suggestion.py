import io
import json
import math
import os
import random

import pandas as pd
import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.distributions as dist
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

MAX_TRAIN_BUDGET = 5000000
Q_MAX_CAP = 512

def _pick_device():
    if not TORCH_AVAILABLE:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"

class PolicyNet(nn.Module if TORCH_AVAILABLE else object):
    def __init__(self, in_features=6, hidden=32, q_max=16):
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required")
        super().__init__()
        self.fc1 = nn.Linear(in_features, hidden)
        self.item_head = nn.Linear(hidden, 1)
        self.qty_head = nn.Linear(hidden, q_max)

    def forward(self, x):
        h = torch.relu(self.fc1(x))
        item_logits = self.item_head(h).squeeze(-1)
        qty_logits = self.qty_head(h)
        return item_logits, qty_logits

class MLSuggest:
    def __init__(self, supabase, fiscal_year):
        self.supabase = supabase
        self.fiscal_year = fiscal_year
        self.baseline = 0.0
        self.policy = None
        self.ml_mins = None
        self.ml_spans = None
        self.device = _pick_device()
        self.bucket = "ml"

        df = pd.DataFrame(self.get_aggregate_data())
        df.drop_duplicates("ItemID", inplace=True)
        df = df.reset_index(drop=True)

        cat_col = "ItemCategory" if "ItemCategory" in df.columns else ("PpmpCategory" if "PpmpCategory" in df.columns else None)
        if cat_col is not None:
            df["IsOffice"] = df[cat_col].fillna("").astype(str).str.upper().str.contains("OFFICE").astype(np.float32)
        else:
            df["IsOffice"] = np.zeros(len(df), dtype=np.float32)

        q_max = int(np.nan_to_num(df["AvailableQuantity"].values.astype(float), nan=0.0).max() or 1)
        self.q_max = min(max(q_max, 1), Q_MAX_CAP)
        self.df = df

    def get_aggregate_data(self):
        return self.supabase.rpc("get_aggregate_for_inlieu", {"fiscal_year": self.fiscal_year}).execute().data

    @staticmethod
    def _normalize(feats, mins=None, spans=None):
        feats = np.asarray(feats, dtype=np.float32)
        feats = np.nan_to_num(feats, nan=0.0, posinf=0.0, neginf=0.0)
        if mins is None:
            mins = feats.min(axis=0)
            spans = feats.max(axis=0) - mins
            spans[spans == 0] = 1.0
        return (feats - mins) / spans, mins, spans

    @staticmethod
    def _individual_score(col):
        lo, hi = col.min(), col.max()
        if hi - lo == 0:
            return pd.Series(.5, index=col.index)
        return (col - lo) / (hi - lo)

    def _feature_matrix(self, budget, avail_remaining=None, mins=None, spans=None):
        df = self.df
        avail = np.nan_to_num(df["AvailableQuantity"].values.astype(np.float32), nan=0.0)
        if avail_remaining is not None:
            avail = np.asarray(avail_remaining, dtype=np.float32)
        base = np.column_stack([
            avail,
            df["PricePerUnit"].values.astype(np.float32),
            df["Frequency"].values.astype(np.float32),
            df["YearlyFrequency"].values.astype(np.float32),
        ])
        X, mins, spans = self._normalize(base, mins, spans)
        office = df["IsOffice"].values.astype(np.float32)
        bnorm = math.log10(max(float(budget or 0.0), 1.0)) / math.log10(MAX_TRAIN_BUDGET)
        budget_col = np.full(len(df), bnorm, dtype=np.float32)
        return np.column_stack([X, office, budget_col]), mins, spans

    def _policy_path(self):
        base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, "ml_suggestion_policy.pt")

    def _storage_client(self):
        return self.supabase.storage.from_(self.bucket)

    def _upload_bytes(self, path, data, content_type="application/octet-stream"):
        try:
            self._storage_client().upload(path, data, {"upsert": "true", "content-type": content_type})
            return True
        except Exception as e:
            print(f"Supabase upload failed ({path}): {e}")
            return False

    def _download_bytes(self, path):
        try:
            return self._storage_client().download(path)
        except Exception:
            return None

    def _load_policy(self):
        try:
            data = self._download_bytes("ml_suggestion_policy.pt")
            if data is None:
                with open(self._policy_path(), "rb") as f:
                    data = f.read()
            ckpt = torch.load(io.BytesIO(data), map_location=self.device, weights_only=False)
            net = PolicyNet(in_features=ckpt["in_features"], hidden=ckpt["hidden"], q_max=ckpt["q_max"])
            net.load_state_dict(ckpt["state"])
            net.to(self.device)
            self.policy = net
            self.ml_mins = ckpt["mins"]
            self.ml_spans = ckpt["spans"]
            self.q_max = ckpt["q_max"]
            return True
        except Exception:
            return False

    def _save_policy(self):
        try:
            buf = io.BytesIO()
            torch.save({
                "state": {k: v.to("cpu") for k, v in self.policy.state_dict().items()},
                "mins": self.ml_mins,
                "spans": self.ml_spans,
                "in_features": self.policy.fc1.in_features,
                "hidden": self.policy.fc1.out_features,
                "q_max": self.q_max,
            }, buf)
            data = buf.getvalue()
            if self._upload_bytes("ml_suggestion_policy.pt", data):
                return
            with open(self._policy_path(), "wb") as f:
                f.write(data)
        except Exception as e:
            print(f"Failed to save suggestion policy: {e}")

    def _ensure_policy(self):
        if self.policy is None and not self._load_policy():
            self.policy = PolicyNet(in_features=6, hidden=32, q_max=self.q_max).to(self.device)
            _, mins, spans = self._feature_matrix(MAX_TRAIN_BUDGET)
            self.ml_mins = mins
            self.ml_spans = spans

    def _rollout(self, budget, sample):
        df = self.df
        prices = df["PricePerUnit"].values.astype(np.float32)
        avail = np.nan_to_num(df["AvailableQuantity"].values.astype(np.float32), nan=0.0).astype(int)
        total_avail = int(avail.sum())
        remaining = float(budget)
        quantities = np.zeros(len(df), dtype=int)
        allocated = np.zeros(len(df), dtype=bool)

        log_p = torch.tensor(0.0, device=self.device)
        entropy = torch.tensor(0.0, device=self.device)
        steps = 0
        max_steps = total_avail + 1

        while steps < max_steps:
            feasible = (avail > 0) & (prices > 0) & (prices <= remaining)
            if not feasible.any():
                break

            X, _, _ = self._feature_matrix(remaining, avail_remaining=avail, mins=self.ml_mins, spans=self.ml_spans)
            item_logits, qty_logits = self.policy(torch.from_numpy(X).to(self.device))
            item_logits = item_logits.masked_fill(~torch.from_numpy(feasible).to(self.device), float("-inf"))
            item_dist = dist.Categorical(logits=item_logits)

            if sample:
                i = int(item_dist.sample().item())
            else:
                i = int(torch.argmax(item_logits).item())

            max_qty = min(int(avail[i]), int(math.floor(remaining / max(prices[i], 1e-9))))
            max_qty = max(max_qty, 1)

            if sample:
                q_logits = qty_logits[i]
                q_mask = torch.zeros(self.q_max, device=self.device)
                q_mask[:min(max_qty, self.q_max)] = 1.0
                q_logits = q_logits.masked_fill(q_mask == 0, float("-inf"))
                q_dist = dist.Categorical(logits=q_logits)
                q = int(q_dist.sample().item()) + 1
                log_p = log_p + item_dist.log_prob(torch.tensor(float(i), device=self.device)) + q_dist.log_prob(torch.tensor(float(q - 1), device=self.device))
                entropy = entropy + item_dist.entropy() + q_dist.entropy()
            else:
                q = max_qty

            quantities[i] += q
            allocated[i] = True
            avail[i] -= q
            remaining -= q * float(prices[i])
            steps += 1

        while remaining > 0:
            candidates = (avail > 0) & (prices > 0)
            if not candidates.any():
                break
            i = int(np.argmin(np.where(candidates, prices, np.inf)))
            if remaining >= float(prices[i]):
                q = min(int(avail[i]), int(math.floor(remaining / max(prices[i], 1e-9))))
            else:
                q = 1
            quantities[i] += q
            allocated[i] = True
            avail[i] -= q
            remaining -= q * float(prices[i])

        return quantities, log_p, entropy, float(budget - remaining), steps

    def _result_df(self, quantities):
        mask = quantities > 0
        cols = ["ItemID", "ItemName", "UnitName", "PricePerUnit", "AvailableQuantity", "Quantity", "Allocation"]
        res = self.df.loc[mask].copy()
        res["Quantity"] = quantities[mask]
        res["Allocation"] = res["Quantity"] * res["PricePerUnit"]
        return res[cols].reset_index(drop=True)

    def _reward(self, result, budget):
        budget = float(budget)
        if budget <= 0:
            return 0.0

        df = self.df
        prices = df["PricePerUnit"].values.astype(float)
        avail = np.nan_to_num(df["AvailableQuantity"].values.astype(float), nan=0.0)
        freq_norm = self._individual_score(df["Frequency"]).values.astype(float)
        stale = (1.0 - self._individual_score(df["YearlyFrequency"]).values).astype(float)
        is_office = df["IsOffice"].values.astype(float)
        closeness = np.clip(1.0 - np.abs(prices - budget) / max(budget, 1e-9), 0.0, 1.0)
        desirability = (closeness + freq_norm + stale + 2.0 * (1.0 - is_office)) / 5.0

        total_cost = float(np.sum(prices * avail))
        total_worth = float(np.sum(desirability))
        budget_factor = min(budget / max(total_cost, 1e-9), 1.0)

        if len(result) == 0:
            return -2.0 * budget_factor

        picked_ids = set(result["ItemID"].tolist())
        picked = np.array(
            [desirability[i] for i, iid in enumerate(df["ItemID"]) if iid in picked_ids],
            dtype=float,
        )
        if len(picked) == 0:
            return -2.0 * budget_factor

        avg_quality = float(picked.mean())
        coverage = float(picked.sum()) / max(total_worth, 1e-9)
        utilization = min(float(result["Allocation"].sum()) / max(budget, 1e-9), 1.0)

        reward = avg_quality + coverage + utilization - 1.0
        if budget_factor > 0.5 and coverage < 0.5:
            reward -= (0.5 - coverage) * budget_factor
        return reward

    def _reward_vs_user(self, result, user_items, budget):
        budget = float(budget)
        if budget <= 0 or not user_items:
            return 0.0

        user_qty = {}
        for item in user_items:
            try:
                user_qty[item["itemId"]] = float(item.get("reduceQuantity", 0) or 0)
            except (KeyError, TypeError, ValueError):
                continue
        user_set = set(user_qty)
        rec_ids = set(result["ItemID"].tolist()) if len(result) else set()

        if not user_set:
            return 0.0

        inter = user_set & rec_ids
        union = user_set | rec_ids
        precision = len(inter) / len(rec_ids) if rec_ids else 0.0
        recall = len(inter) / len(user_set)
        f1 = 2.0 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        qty_scores = []
        for iid in inter:
            q_user = user_qty[iid]
            q_rec = float(result.loc[result["ItemID"] == iid, "Quantity"].iloc[0])
            qty_scores.append(1.0 - min(abs(q_rec - q_user) / max(q_user, 1.0), 1.0))
        qty_sim = float(np.mean(qty_scores)) if qty_scores else 0.0

        spent = float(result["Allocation"].sum()) if len(result) else 0.0
        budget_score = min(spent / max(float(budget), 1e-9), 1.0)

        return f1 + qty_sim + budget_score

    def learn_from_decision(self, user_items, budget, n_steps=20, lr=0.01, entropy_bonus=0.05, baseline_decay=0.9):
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required")
        if not user_items or float(budget) <= 0:
            return self.policy

        self._ensure_policy()
        self.policy.train()
        optimizer = torch.optim.Adam(self.policy.parameters(), lr=lr)

        rewards = []
        for _ in range(n_steps):
            quantities, log_p, entropy, _, steps_taken = self._rollout(float(budget), sample=True)
            result = self._result_df(quantities)
            reward = self._reward_vs_user(result, user_items, budget)
            rewards.append(reward)

            self.baseline = baseline_decay * self.baseline + (1.0 - baseline_decay) * reward

            if steps_taken == 0:
                continue

            advantage = reward - self.baseline
            loss = -advantage * log_p - entropy_bonus * entropy
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        self.policy.eval()
        self._save_policy()
        print(f"learn_from_decision: avg reward {float(np.mean(rewards)):.4f} over {n_steps} steps")
        return self.policy

    def learn_from_rejection(self, rejected_items, budget, n_steps=20, lr=0.01, entropy_bonus=0.05, baseline_decay=0.9):
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required")
        if not rejected_items or float(budget) <= 0:
            return self.policy

        self._ensure_policy()
        self.policy.train()
        optimizer = torch.optim.Adam(self.policy.parameters(), lr=lr)

        rewards = []
        for _ in range(n_steps):
            quantities, log_p, entropy, _, steps_taken = self._rollout(float(budget), sample=True)
            result = self._result_df(quantities)
            reward = -self._reward_vs_user(result, rejected_items, budget)
            rewards.append(reward)

            self.baseline = baseline_decay * self.baseline + (1.0 - baseline_decay) * reward

            if steps_taken == 0:
                continue

            advantage = reward - self.baseline
            loss = -advantage * log_p - entropy_bonus * entropy
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        self.policy.eval()
        self._save_policy()
        print(f"learn_from_rejection: avg reward {float(np.mean(rewards)):.4f} over {n_steps} steps")
        return self.policy

    def _last_rec_path(self):
        base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, "last_recommendation.json")

    def save_last_recommendation(self, result, budget):
        try:
            payload = {
                "budget": float(budget),
                "fiscal_year": self.fiscal_year,
                "items": [{
                    "itemId": row["ItemID"],
                    "itemName": row["ItemName"],
                    "reduceQuantity": int(row["Quantity"]),
                    "priceCatalog": float(row["PricePerUnit"]),
                } for _, row in result.iterrows()],
            }
            data = json.dumps(payload).encode("utf-8")
            if self._upload_bytes("last_recommendation.json", data, "application/json"):
                return
            with open(self._last_rec_path(), "w") as f:
                json.dump(payload, f)
        except Exception as e:
            print(f"Failed to save last recommendation: {e}")

    def load_last_recommendation(self):
        try:
            data = self._download_bytes("last_recommendation.json")
            if data is None:
                with open(self._last_rec_path(), "r") as f:
                    return json.load(f)
            return json.loads(data.decode("utf-8"))
        except Exception:
            return None

    def clear_last_recommendation(self):
        try:
            self._storage_client().remove(["last_recommendation.json"])
        except Exception:
            pass
        try:
            if os.path.exists(self._last_rec_path()):
                os.remove(self._last_rec_path())
        except Exception:
            pass

    def train(self, n_steps=200, lr=0.01, entropy_bonus=0.05, baseline_decay=0.9, max_budget=MAX_TRAIN_BUDGET):
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required")

        self._ensure_policy()
        self.policy.train()
        optimizer = torch.optim.Adam(self.policy.parameters(), lr=lr)

        rewards = []
        for step in range(n_steps):
            budget = math.exp(random.uniform(0.0, math.log(max_budget)))
            budget = max(900.0, budget)

            quantities, log_p, entropy, _, steps = self._rollout(budget, sample=True)
            result = self._result_df(quantities)
            reward = self._reward(result, budget)
            rewards.append(reward)

            self.baseline = baseline_decay * self.baseline + (1.0 - baseline_decay) * reward

            if steps == 0:
                continue

            advantage = reward - self.baseline
            loss = -advantage * log_p - entropy_bonus * entropy
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            if (step + 1) % max(1, n_steps // 10) == 0:
                avg = sum(rewards[-max(1, n_steps // 10):]) / max(1, n_steps // 10)
                print(f"step {step + 1}/{n_steps}: avg reward {avg:.4f}")

        self.policy.eval()
        self._save_policy()
        return self.policy

    def ml_self_train(self):
        self.train()

    def _force_fill(self, budget):
        df = self.df
        prices = df["PricePerUnit"].values.astype(np.float32)
        avail = np.nan_to_num(df["AvailableQuantity"].values.astype(np.float32), nan=0.0).astype(int)
        remaining = float(budget)
        quantities = np.zeros(len(df), dtype=int)
        while remaining > 0:
            candidates = (avail > 0) & (prices > 0)
            if not candidates.any():
                break
            i = int(np.argmin(np.where(candidates, prices, np.inf)))
            if remaining >= float(prices[i]):
                q = min(int(avail[i]), int(math.floor(remaining / max(prices[i], 1e-9))))
            else:
                q = 1
            quantities[i] += q
            avail[i] -= q
            remaining -= q * float(prices[i])
        return quantities

    def recommend(self, budget):
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required")

        self._ensure_policy()
        self.policy.eval()

        if budget <= 0:
            empty = pd.DataFrame(columns=["ItemID", "ItemName", "UnitName", "PricePerUnit", "AvailableQuantity", "Quantity", "Allocation"])
            return empty

        budget = float(budget)
        prices = self.df["PricePerUnit"].values.astype(float)
        avail = np.nan_to_num(self.df["AvailableQuantity"].values.astype(float), nan=0.0)
        pool = float(np.sum(prices * avail))
        if pool < budget:
            raise Exception("The total available items cannot meet the required budget.")

        with torch.no_grad():
            quantities, _, _, _, _ = self._rollout(budget, sample=False)
        res = self._result_df(quantities)

        spent = float(res["Allocation"].sum()) if len(res) else 0.0
        if spent < budget:
            quantities = self._force_fill(budget)
            res = self._result_df(quantities)
            spent = float(res["Allocation"].sum()) if len(res) else 0.0
            if spent < budget:
                raise Exception("The total available items cannot meet the required budget.")
        return res
