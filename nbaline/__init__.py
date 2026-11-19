"""NBALine: predicts NBA player props (points, rebounds, assists, ...) as calibrated over/under
probabilities, and helps build and grade PrizePicks entries.

How the pieces fit together:

    fetch box scores  ->  features.py  ->  modeling.py  ->  predictor.py  ->  web app / CLI
    (stats.nba.com)       model inputs     XGBoost + NN     player + line       Best lines,
                          from past games  + uncertainty    -> P(over)          Check lines

    schedule.py / injuries.py   official schedule and injury report, used for every prediction
    pickem/                     PrizePicks: payouts, reading a pasted board, ranking, saving + grading
    recipes.py                  the model settings chosen by the experiments (experiments.py)
    updater.py                  the one-click "update data & model" job behind the web app
"""
