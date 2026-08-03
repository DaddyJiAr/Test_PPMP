import joblib
from ortools.sat.python import cp_model
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
import pandas as pd
from ortools.sat.python import cp_model

def get_x_y(training_rows):
    df = pd.DataFrame(training_rows)
    X = df[
        [
            "InLieuTotalQuantity",
            "PlannedQuantity",
            "AvailableQuantity",
        ]
    ]
    Y = df["TargetWasCut"]
    return X, Y

def split(X, Y):
    X_train, X_test, Y_train, y_test = train_test_split(
        X,
        Y,
        test_size=0.2,
        random_state=42
    )
    return X_train, X_test, Y_train, y_test

def model(X_train, Y_train):
    model = RandomForestClassifier(random_state=42)
    model.fit(X_train, Y_train)
    return model

def test(X_test, Y_test, model):
    predictions = model.predict(X_test)
    print(confusion_matrix(Y_test, predictions))
    print(classification_report(Y_test, predictions))
    print(accuracy_score(Y_test, predictions))

def save_model(model):
    joblib.dump(model, "in_lieu_model.pkl")

def lahat(training_rows):
    df = pd.DataFrame(training_rows)
    X = df[
        [
            "InLieuTotalQuantity",
            "PlannedQuantity",
            "AvailableQuantity",
        ]
    ]
    Y = df["TargetWasCut"]
    X_train, X_test, Y_train, Y_test = train_test_split(
        X,
        Y,
        test_size=0.2,
        random_state=42
    )
    # model = RandomForestClassifier(random_state=42)
    # model.fit(X_train, Y_train)
    model = joblib.load("in_lieu_model.pkl")
    predictions = model.predict(X_test)
    # print(confusion_matrix(Y_test, predictions))
    # print(classification_report(Y_test, predictions))
    # print(accuracy_score(Y_test, predictions))
    prediction_data = df.drop(columns=["WasReduced"])
    probabilities = model.predict_proba(X_train)
    # print(probabilities)
    return probabilities

def reverse_knapsack(items, target_budget):

    model = cp_model.CpModel()

    x = []

    for i in range(len(items)):
        x.append(model.NewBoolVar(f"x{i}"))

    # Must reach target

    model.Add(
        sum(
            x[i] * items[i]["BudgetImpact"]
            for i in range(len(items))
        ) >= target_budget
    )

    SCALE = 1000

    model.Maximize(
        sum(
            x[i] * int(items[i]["AI_Score"] * SCALE)
            for i in range(len(items))
        )
    )

    solver = cp_model.CpSolver()

    solver.Solve(model)

    chosen = []

    for i in range(len(items)):
        if solver.Value(x[i]):
            chosen.append(items[i])

    return chosen