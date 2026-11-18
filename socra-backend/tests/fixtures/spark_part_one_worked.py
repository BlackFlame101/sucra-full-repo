"""Hand-authored French response for the original Spark Part 1 PDF, pages 2–5."""

LESSONS = (
    """Le parcours part du fichier brut et se termine par une décision que l’on peut expliquer. On contrôle d’abord ce qui entre dans le modèle, puis on apprend les transformations et les coefficients sur l’entraînement. La validation sert aux choix et le test sert au bilan final. Suivez le lien de prérequis pour démarrer Spark avant la première cellule. Le TP utilise une étiquette synthétique : un bon score renseigne sur ce scénario pédagogique, sans établir la fiabilité d’un système bancaire réel.""",
    """Chaque ligne associe un identifiant et des caractéristiques observables à une étiquette `fraude`. Le générateur combine notamment le montant, le pays et les tentatives dans un score, ajoute un bruit gaussien, puis attribue la classe en comparant le score à un seuil. Le bruit empêche les caractéristiques de déterminer parfaitement la classe. Le montant est aussi mis à `None` sur certaines lignes, ce qui permet de mettre à l’épreuve le nettoyage.

Exécutez cette cellule dans le notebook après avoir démarré Spark. Elle n’écrit le fichier que s’il n’existe pas déjà. Le chemin affiché permet de contrôler quel fichier est utilisé ; si le notebook réutilise une ancienne version, la graine seule ne régénère rien. Après création, ouvrez un extrait pour vérifier que chaque ligne non vide peut être lue comme un objet JSON indépendant.""",
    """La lecture traduit les champs JSON en colonnes Spark. On choisit `LongType` pour l’identifiant, des types entiers pour les caractéristiques discrètes et `DoubleType` pour le montant et l’étiquette. Le schéma fixe les types attendus et évite de dépendre des valeurs rencontrées lors d’une inférence. Il n’impose pas à lui seul les règles métier : ici les champs restent nullables et l’étape suivante éliminera les lignes inexploitables.

Comparez `printSchema()` aux types déclarés et inspectez les lignes affichées. Le tableau `groupBy("fraude").count()` fournit le point de départ du diagnostic de déséquilibre. Sa sortie dépend du fichier effectivement chargé.""",
    """Une ligne JSON Lines constitue un enregistrement indépendant : Spark peut lire ces enregistrements sans reconstruire un document JSON unique. Un tableau JSON réparti sur plusieurs lignes ne suit pas cette convention. Pour ce type de fichier, utilisez `spark.read.option("multiLine", True).schema(schema_tx).json(...)` afin que Spark le lise comme un document multiligne. Conservez le schéma explicite dans les deux cas pour vérifier la même structure.

La cible est `fraude`, connue au moment de l’entraînement et utilisée pour évaluer les prédictions. Les entrées sont `montant`, `heure`, `pays_different` et `nb_tentatives`. L’identifiant sert à retrouver une transaction lors du contrôle et de l’export. Le mettre dans le vecteur ferait dépendre le modèle d’un numéro attribué par le générateur.""",
    """Le filtre SQL garde les observations dont les valeurs sont compatibles avec les contraintes du TP. Par exemple, la comparaison `montant > 0` n’est pas vraie pour un montant nul au sens SQL ; la ligne est donc écartée. `SELECT DISTINCT` retire les lignes entièrement identiques ; si deux enregistrements partagent un identifiant avec d’autres valeurs différentes, cette instruction ne règle pas ce conflit.

Après les contrôles, `randomSplit` affecte des observations à l’entraînement, à la validation et au test. Comparez les comptes avant et après filtrage, puis les effectifs par classe dans chaque jeu. Le jeu d’entraînement ajuste les paramètres, la validation compare les candidats et le test reste indépendant des choix. La graine facilite la reproduction avec les mêmes entrées.""",
    """L’entraînement a besoin d’exemples des deux classes pour apprendre leur séparation. Une validation ou un test sans fraude ne permet pas de mesurer le rappel de la fraude, et sans l’une des classes une comparaison de classement par AUC ne peut pas être interprétée. Imprimez donc les comptes réels avant de lire les scores. Les poids de `randomSplit` donnent des proportions cibles et la méthode ne garantit ni des effectifs exacts ni une stratification par classe.

Pour une prédiction future, découpez en périodes successives définies à l’avance : passé pour l’entraînement, période suivante pour la validation, période la plus récente pour le test. Calculez les caractéristiques avec les seules informations disponibles au moment de chaque transaction. Un découpage aléatoire pourrait laisser des tendances futures influencer les décisions prises pour le passé.""",
    """**Du tableau au modèle.** Les estimateurs de Spark ML reçoivent une colonne vectorielle de caractéristiques par ligne. `VectorAssembler` assemble les colonnes dans l’ordre de `features_tx` et écrit `features_brutes`. La position dans le vecteur relie chaque coefficient à sa variable. L’assembleur est un transformateur : il applique cette règle sans apprendre de paramètres.

**Mise à l’échelle.** Les montants et les variables discrètes n’ont pas les mêmes amplitudes. `StandardScaler` apprend l’écart type de chaque composante sur `train_tx`, puis les transformations réutilisent ces statistiques. Avec `withMean=False` la moyenne n’est pas soustraite ; la mise à l’échelle par écart type reste active avec la configuration du TP. Cela évite le centrage, qui peut densifier un vecteur creux. Une échelle comparable rend aussi les coefficients et leur régularisation plus faciles à interpréter.

**Apprentissage et réutilisation.** La régression logistique apprend des coefficients et une constante qui relient les caractéristiques au log-rapport de chances de fraude. La fonction logistique traduit ce score en probabilité estimée. `Pipeline` ordonne les transformations et les estimateurs. `fit(train_tx)` applique l’assembleur, ajuste le normaliseur, transforme les vecteurs d’entraînement, puis ajuste le classifieur. Le `PipelineModel` obtenu contient les étapes prêtes à appliquer. `transform(valid_tx)` produit des scores et des prédictions avec les paramètres déjà appris. Inspectez les colonnes `features`, `probability` et `prediction` avant de comparer les modèles à l’étape suivante.""",
    """L’identifiant est un numéro de suivi, sans signification comportementale. L’inclure rendrait possible l’apprentissage d’une relation fortuite avec l’ordre de génération. On le conserve pour rapprocher les prédictions des lignes d’origine.

Apprendre les écarts types sur tous les jeux ferait intervenir la distribution de la validation et du test avant le choix du modèle. Cette fuite peut rendre l’évaluation trop optimiste. Gardez donc les mêmes statistiques d’entraînement pour toutes les prédictions. Le `Pipeline` est la recette qui contient notamment les estimateurs non ajustés ; le `PipelineModel` contient leurs versions ajustées et permet de transformer de nouvelles observations sans refaire `fit`.""",
    """La régression logistique utilise une frontière linéaire dans l’espace des caractéristiques. L’arbre apprend des seuils successifs et peut saisir des interactions ; la forêt combine des arbres pour atténuer la dépendance à un seul arbre. Le TP ajuste chaque pipeline sur le même `train_tx` et évalue chaque candidat sur le même `valid_tx` afin de comparer les méthodes dans les mêmes conditions.

L’accuracy donne la proportion de classes correctement prédites. Le F1 de chaque classe est la moyenne harmonique de sa précision et de son rappel ; Spark agrège ici ces F1 en les pondérant par les effectifs réels de chaque classe. L’AUC ROC examine le classement des positifs par rapport aux négatifs à partir des scores, sur l’ensemble des seuils. Un modèle peut avoir une bonne accuracy en prédisant presque toujours la classe majoritaire. Lisez en plus la matrice des comptes `fraude` × `prediction` pour voir les erreurs sur la classe fraude.

**Cellule originale du PDF.** Le constructeur de `BinaryClassificationEvaluator` y reçoit deux fois le mot-clé `labelCol`. Python refuse cet appel à la compilation. La cellule d’origine est conservée ci-dessous pour comparaison.""",
    """Un faux négatif laisse passer une fraude. Le rappel positif rapporte les fraudes détectées à toutes les fraudes réelles. La précision positive rapporte les fraudes détectées à toutes les alertes. Abaisser le seuil de classement peut repérer davantage de fraudes, avec plus de faux positifs à traiter. Par exemple, une équipe d’enquête de capacité limitée peut analyser le rappel atteignable à un niveau de précision compatible avec son volume d’alertes.

Comparez les candidats avec un critère fixé avant d’ouvrir le test. Si les résultats du test servent à changer le seuil ou le modèle, ils ont servi à la sélection et ne fournissent plus le même contrôle indépendant. L’Exercice A reprend ce principe pour comparer des hyperparamètres ; son unique évaluation finale concerne la configuration retenue sur sa propre validation.""",
    """La cellule reprend `pred_test_tx`, issu du modèle sélectionné à l’étape précédente. La requête SQL calcule par classe réelle la proportion d’observations correctement classées : le taux de la classe fraude correspond à son rappel. Le fichier créé avec le séparateur `;` garde l’identifiant, la classe réelle, la classe prédite et les deux probabilités. Vérifiez le chemin affiché, l’en-tête, le nombre de lignes utiles et la cohérence entre une ligne du CSV et le DataFrame affiché.

Le vecteur `probability` permet de distinguer deux alertes qui ont la même étiquette prédite mais des niveaux de confiance différents. Pour choisir un autre modèle ou ajuster un seuil, revenez à la validation ; le CSV du test décrit le résultat final du protocole.""",
    """`collect()` matérialise toutes les lignes dans une liste côté pilote. `toLocalIterator()` permet de les traiter au fil de l’itération ; la mémoire nécessaire dépend notamment de la taille de la plus grande partition. Chaque ligne passe encore par le pilote, qui écrit un seul fichier. Pour un gros volume, un export réparti par Spark répartit l’écriture et produit des fichiers par partition.

`probability[0]` estime la probabilité de la classe sans fraude et `probability[1]` celle de la classe fraude, dans l’ordre des étiquettes du TP. Les deux valeurs décrivent le même choix binaire et leur somme vaut un à l’arrondi près. Une forte probabilité n’est pas une preuve de fraude ; confrontez les scores aux étiquettes et aux erreurs observées.""",
    """**Configurations.** L’arbre est testé avec `maxDepth=3` puis `8`. La forêt combine `numTrees` dans `{15, 60}` avec `maxDepth` dans `{4, 8}`. `maxDepth` borne le nombre de niveaux de divisions : une profondeur accrue permet de représenter des interactions plus fines, au prix d’un risque accru de surajustement. `numTrees` règle le nombre d’arbres agrégés. Une forêt plus grande peut stabiliser les votes mais coûte plus à entraîner et à appliquer.

**Protocole.** Réutilisez les DataFrames `train_tx`, `valid_tx`, `test_tx` de l’étape 3 ainsi que `assembleur_tx` et `normaliseur_tx` de l’étape 4. Chaque pipeline est ajusté uniquement sur `train_tx`. La cellule produit le tableau demandé sur `valid_tx` avec le F1 pondéré, l’accuracy et l’AUC ROC. Elle retient le F1 pondéré le plus élevé ; une égalité est départagée par le premier candidat dans l’ordre du tableau. Ensuite, le modèle choisi transforme une seule fois `test_tx`, sans nouvelle recherche de configuration. Exécutez la cellule pour remplir le tableau avec vos propres valeurs.""",
)

CLAIMS = (
    "Le parcours part du fichier brut et se termine par une décision que l’on peut expliquer.",
    "Chaque ligne associe un identifiant et des caractéristiques observables à une étiquette `fraude`.",
    "La lecture traduit les champs JSON en colonnes Spark.",
    "Une ligne JSON Lines constitue un enregistrement indépendant : Spark peut lire ces enregistrements sans reconstruire un document JSON unique.",
    "Le filtre SQL garde les observations dont les valeurs sont compatibles avec les contraintes du TP.",
    "L’entraînement a besoin d’exemples des deux classes pour apprendre leur séparation.",
    "Les estimateurs de Spark ML reçoivent une colonne vectorielle de caractéristiques par ligne.",
    "L’inclure rendrait possible l’apprentissage d’une relation fortuite avec l’ordre de génération.",
    "Le TP ajuste chaque pipeline sur le même `train_tx` et évalue chaque candidat sur le même `valid_tx` afin de comparer les méthodes dans les mêmes conditions.",
    "Le rappel positif rapporte les fraudes détectées à toutes les fraudes réelles.",
    "La requête SQL calcule par classe réelle la proportion d’observations correctement classées : le taux de la classe fraude correspond à son rappel.",
    "`toLocalIterator()` permet de les traiter au fil de l’itération ; la mémoire nécessaire dépend notamment de la taille de la plus grande partition.",
    "La cellule produit le tableau demandé sur `valid_tx` avec le F1 pondéré, l’accuracy et l’AUC ROC.",
)

EXERCISE_CODE = """from pyspark.ml import Pipeline
from pyspark.ml.classification import DecisionTreeClassifier, RandomForestClassifier
from pyspark.ml.evaluation import MulticlassClassificationEvaluator, BinaryClassificationEvaluator

f1 = MulticlassClassificationEvaluator(labelCol="fraude", predictionCol="prediction", metricName="f1")
accuracy = MulticlassClassificationEvaluator(labelCol="fraude", predictionCol="prediction", metricName="accuracy")
auc = BinaryClassificationEvaluator(labelCol="fraude", rawPredictionCol="rawPrediction", metricName="areaUnderROC")

candidats = [
    ("Arbre", f"maxDepth={profondeur}", DecisionTreeClassifier(labelCol="fraude", maxDepth=profondeur, seed=73))
    for profondeur in (3, 8)
]
candidats += [
    ("Forêt", f"numTrees={arbres}, maxDepth={profondeur}",
     RandomForestClassifier(labelCol="fraude", maxDepth=profondeur, numTrees=arbres, seed=73))
    for arbres in (15, 60) for profondeur in (4, 8)
]

def mesures(predictions):
    return f1.evaluate(predictions), accuracy.evaluate(predictions), auc.evaluate(predictions)

comparaisons = []
for nom, parametres, estimateur in candidats:
    pipeline = Pipeline(stages=[assembleur_tx, normaliseur_tx, estimateur])
    modele = pipeline.fit(train_tx)
    scores = mesures(modele.transform(valid_tx))
    comparaisons.append((nom, parametres, scores, modele))

print(f'{"Algorithme":<12} {"Paramètres":<26} {"F1":>8} {"Accuracy":>8} {"AUC":>8}')
for nom, parametres, (f1_val, acc_val, auc_val), _ in comparaisons:
    print(f"{nom:<12} {parametres:<26} {f1_val:8.4f} {acc_val:8.4f} {auc_val:8.4f}")

nom, parametres, scores_valid, modele_final = max(comparaisons, key=lambda comparaison: comparaison[2][0])
predictions_finales = modele_final.transform(test_tx).cache()
try:
    print(f"Configuration choisie sur validation : {nom}, {parametres}")
    print("F1, accuracy, AUC sur test :", mesures(predictions_finales))
    predictions_finales.groupBy("fraude", "prediction").count().show()
finally:
    predictions_finales.unpersist()"""

EXERCISE_INTERPRETATION = """**Lecture attendue.** Le tableau de validation contient une ligne par configuration. Les valeurs numériques seront calculées dans votre notebook. Comparez le F1 final au F1 obtenu sur validation pour le même candidat, puis lisez les faux négatifs dans la matrice de confusion. Si le F1 global est correct mais que beaucoup de fraudes passent, signalez la limite du F1 pondéré dans la conclusion. Un écart validation–test peut venir du hasard du découpage ou de différences de distribution ; consignez-le sans relancer la sélection sur le test.

**À retenir.** Ajustez les transformations et le classifieur sur l’entraînement, prenez les décisions sur validation et utilisez le test pour rendre compte de la performance finale. Les résultats sont des observations du jeu synthétique, avec le contexte et les limites de ce jeu."""
