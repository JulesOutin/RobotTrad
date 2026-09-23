# RobotTrad

Robot de trading pédagogique sur des actions éligibles au PEA, fondé sur le croisement de deux moyennes mobiles.
**Aucun ordre réel n'est passé** : le robot calcule des signaux, vous décidez et passez les ordres vous-même.

## Ce que fait le dépôt

Chaque soir de semaine, GitHub Actions :
1. calcule les signaux du jour et les ajoute à `journal_signaux.csv` ;
2. génère le rapport HTML (ordres pour le lendemain, backtest, courbes, robustesse) ;
3. publie ce rapport sur GitHub Pages, consultable depuis un téléphone.

## Mise en route (une seule fois)

1. **Settings → Pages** : dans *Build and deployment*, choisir la source **GitHub Actions**.
2. **Actions → Robot du soir → Run workflow** pour un premier lancement.
3. Le rapport est ensuite disponible à l'adresse `https://julesoutin.github.io/RobotTrad/`.

Le dépôt étant public, la page du rapport l'est aussi.

## Utilisation sur ordinateur

```
pip install -r requirements.txt
python robot_actions.py
```

Autres modes : `backtest`, `robustesse`, `signaux`, choisis en modifiant `MODE` dans le fichier
ou via la variable d'environnement `ROBOT_MODE`.

## Paramètres

Tout se règle en haut de `robot_actions.py` : liste des actions, moyennes mobiles, frais, stop-loss, période de test.

## Avertissement

Projet d'apprentissage. Les performances passées ne préjugent pas des performances futures ; ce code ne constitue pas un conseil en investissement.
