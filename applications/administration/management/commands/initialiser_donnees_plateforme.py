"""
Commande d'initialisation des données réelles de la plateforme AYYOU à Dakar.

Peuple la base de données avec :
- Les catégories officielles (Plats, Burgers, Poulet, Poisson, Desserts, Boissons)
- Les utilisateurs réels pour les 4 rôles métier (Client, Restaurant, Livreur, Superadmin)
- Les restaurants partenaires réels (Le Teranga Gourmand, Chez L'Habitant)
- Les plats réels avec tarifs FCFA, descriptions et photos
- Les publications réelles de vidéos/photos culinaires
- Une commande réelle pour tester le flux de bout en bout
"""

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify

from applications.communs.choix import StatutValidationPartenaire
from applications.utilisateurs.models import Role
from applications.etablissements.models import Etablissement, TypeEtablissement
from applications.catalogue.models import CategoriePlat, Plat, SectionMenu
from applications.livraisons.models import ProfilLivreur, TypeVehicule, DisponibiliteLivreur
from applications.publications.models import Publication, TypeMedia
from applications.commandes.models import Commande, LigneCommande, StatutCommande, ModePaiement

Utilisateur = get_user_model()


class Command(BaseCommand):
    help = "Initialise la base de données AYYOU avec des données réelles dakaroises."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Démarrage de l'initialisation des données AYYOU..."))

        # 1. Catégories officielles
        categories_data = [
            ("Plats", "fa-solid fa-utensils", "bg-rose-50", "text-[#E51824]"),
            ("Burgers", "fa-solid fa-burger", "bg-rose-50", "text-[#E51824]"),
            ("Poulet", "fa-solid fa-drumstick-bite", "bg-rose-50", "text-[#E51824]"),
            ("Poisson", "fa-solid fa-fish", "bg-rose-50", "text-[#E51824]"),
            ("Desserts", "fa-solid fa-ice-cream", "bg-rose-50", "text-[#E51824]"),
            ("Boissons", "fa-solid fa-bottle-water", "bg-rose-50", "text-[#E51824]"),
        ]
        categories_dict = {}
        for idx, (nom, icone, bg, color) in enumerate(categories_data, start=1):
            cat, _ = CategoriePlat.objects.update_or_create(
                nom=nom,
                defaults={
                    "slug": slugify(nom),
                    "icone": icone,
                    "couleur_fond": bg,
                    "couleur_texte": color,
                    "ordre": idx,
                }
            )
            categories_dict[nom] = cat
        self.stdout.write(self.style.SUCCESS(f"{len(categories_dict)} catégories créées/mises à jour."))

        # 2. Utilisateurs pour chaque rôle
        # Superadmin
        admin, _ = Utilisateur.objects.update_or_create(
            courriel="admin@ayyou.sn",
            defaults={
                "prenom": "Admin",
                "nom": "AYYOU",
                "telephone": "+221775678901",
                "role": Role.ADMINISTRATEUR,
                "is_staff": True,
                "is_superuser": True,
            }
        )
        admin.set_password("MotDePasse!2026")
        admin.save()

        # Client
        client, _ = Utilisateur.objects.update_or_create(
            courriel="fatou.diop@ayyou.sn",
            defaults={
                "prenom": "Fatou",
                "nom": "Diop",
                "telephone": "+221771234567",
                "role": Role.CLIENT,
                "adresse": "Almadies, Villa 45, Dakar",
                "preferences_alimentaires": ["Thieboudienne", "Poisson", "Pastels"],
            }
        )
        client.set_password("MotDePasse!2026")
        client.save()

        # Restaurant (Gérant)
        gerant_teranga, _ = Utilisateur.objects.update_or_create(
            courriel="contact@teranga-gourmand.sn",
            defaults={
                "prenom": "Cheikh",
                "nom": "Ndiaye",
                "telephone": "+221772345678",
                "role": Role.RESTAURANT,
                "adresse": "Plateau, Rue Carnot, Dakar",
            }
        )
        gerant_teranga.set_password("MotDePasse!2026")
        gerant_teranga.save()

        # Livreur
        livreur_user, _ = Utilisateur.objects.update_or_create(
            courriel="moussa.express@ayyou.sn",
            defaults={
                "prenom": "Moussa",
                "nom": "Ba",
                "telephone": "+221774567890",
                "role": Role.LIVREUR,
                "adresse": "Médina, Dakar",
            }
        )
        livreur_user.set_password("MotDePasse!2026")
        livreur_user.save()

        profil_livreur, _ = ProfilLivreur.objects.update_or_create(
            utilisateur=livreur_user,
            defaults={
                "type_vehicule": TypeVehicule.MOTO,
                "nom_vehicule": "Yamaha TMAX",
                "immatriculation": "DK-4582-AZ",
                "zone_principale": "Plateau & Corniche",
                "statut_validation": StatutValidationPartenaire.ACTIF,
                "disponibilite": DisponibiliteLivreur.EN_LIGNE,
                "latitude": Decimal("14.6928"),
                "longitude": Decimal("-17.4467"),
                "date_derniere_position": timezone.now(),
            }
        )

        self.stdout.write(self.style.SUCCESS("4 comptes réels (Client, Restaurant, Livreur, Admin) créés avec mot de passe MotDePasse!2026."))

        # Restaurant 2 (Chez L'Habitant)
        gerant_habitant, _ = Utilisateur.objects.update_or_create(
            courriel="contact@chezlhabitant.sn",
            defaults={
                "prenom": "Abdoulaye",
                "nom": "Diallo",
                "telephone": "+221773456789",
                "role": Role.RESTAURANT,
                "adresse": "Keur Massar, Rond point 6, Dakar",
            }
        )
        gerant_habitant.set_password("MotDePasse!2026")
        gerant_habitant.save()

        # 3. Établissements réels
        resto_teranga, _ = Etablissement.objects.update_or_create(
            nom_utilisateur="terangagourmand",
            defaults={
                "gerant": gerant_teranga,
                "type_etablissement": TypeEtablissement.RESTAURANT,
                "nom": "Le Teranga Gourmand",
                "description": "Cuisine authentique dakaroise, spécialités sénégalaises d'excellence.",
                "specialite": "Cuisine sénégalaise et grillades",
                "adresse": "Rue Carnot, Plateau",
                "quartier_ville": "Plateau",
                "latitude": Decimal("14.6685"),
                "longitude": Decimal("-17.4372"),
                "heure_ouverture": "09:00:00",
                "heure_fermeture": "23:30:00",
                "est_ouvert": True,
                "statut_validation": StatutValidationPartenaire.ACTIF,
                "frais_livraison_fcfa": 1000,
                "delai_livraison_texte": "20-30 min",
            }
        )

        resto_habitant, _ = Etablissement.objects.update_or_create(
            nom_utilisateur="chezlhabitant",
            defaults={
                "gerant": gerant_habitant,
                "type_etablissement": TypeEtablissement.RESTAURANT,
                "nom": "Chez L'Habitant",
                "description": "Plats traditionnels généreux préparés au feu de bois.",
                "specialite": "Thieboudienne et Yassa fait maison",
                "adresse": "Keur Massar, Rond point 6",
                "quartier_ville": "Keur Massar",
                "latitude": Decimal("14.7785"),
                "longitude": Decimal("-17.3122"),
                "heure_ouverture": "10:00:00",
                "heure_fermeture": "22:00:00",
                "est_ouvert": True,
                "statut_validation": StatutValidationPartenaire.ACTIF,
                "frais_livraison_fcfa": 1000,
                "delai_livraison_texte": "25-35 min",
            }
        )

        # 4. Plats réels
        plats_data = [
            {
                "etablissement": resto_teranga,
                "categorie": categories_dict["Plats"],
                "section": SectionMenu.PLATS_PRINCIPAUX,
                "nom": "Thieboudienne Royal",
                "description": "Riz rouge sénégalais au mérou blanc frais, carottes, manioc, chou et sauce beugueudj onctueuse.",
                "prix": 3500,
                "est_disponible": True,
            },
            {
                "etablissement": resto_teranga,
                "categorie": categories_dict["Poulet"],
                "section": SectionMenu.PLATS_PRINCIPAUX,
                "nom": "Yassa au Poulet Confit",
                "description": "Cuisse de poulet fermier braisée puis marinée aux citrons verts et oignons dorés caramélisés.",
                "prix": 3000,
                "est_disponible": True,
            },
            {
                "etablissement": resto_teranga,
                "categorie": categories_dict["Plats"],
                "section": SectionMenu.PLATS_PRINCIPAUX,
                "nom": "Pastels Dorés au Thon (6 pcs)",
                "description": "Petits chaussons croustillants dorés servis avec sauce tomate pimentée maison.",
                "prix": 1500,
                "est_disponible": True,
            },
            {
                "etablissement": resto_teranga,
                "categorie": categories_dict["Boissons"],
                "section": SectionMenu.BOISSONS,
                "nom": "Bissap Frais Maison",
                "description": "Jus naturel d'hibiscus infusé à la menthe fraîche et fleur d'oranger, 50cl.",
                "prix": 1000,
                "est_disponible": True,
            },
            {
                "etablissement": resto_habitant,
                "categorie": categories_dict["Plats"],
                "section": SectionMenu.PLATS_PRINCIPAUX,
                "nom": "Mafe au Bœuf Fondant",
                "description": "Morceaux de bœuf mijotés dans une sauce onctueuse à la pâte d'arachide dakaroise.",
                "prix": 3200,
                "est_disponible": True,
            },
            {
                "etablissement": resto_habitant,
                "categorie": categories_dict["Burgers"],
                "section": SectionMenu.PLATS_PRINCIPAUX,
                "nom": "Burger Teranga Dakar",
                "description": "Steak pur bœuf assaisonné au poivre de Selim, oignons confits au citron et cheddar.",
                "prix": 4200,
                "est_disponible": True,
            },
        ]

        plats_crees = []
        for p in plats_data:
            plat, _ = Plat.objects.update_or_create(
                nom=p["nom"],
                etablissement=p["etablissement"],
                defaults={
                    "categorie": p["categorie"],
                    "section_menu": p["section"],
                    "description": p["description"],
                    "prix_fcfa": p["prix"],
                    "est_disponible": p["est_disponible"],
                }
            )
            plats_crees.append(plat)
        self.stdout.write(self.style.SUCCESS(f"{len(plats_crees)} plats créés/mis à jour."))

        # 5. Publications réelles
        Publication.objects.all().delete()
        pubs_data = [
            (resto_teranga, plats_crees[0], "Thieboudienne Royal mijoté", "Notre Thieboudienne Royal mijoté selon la tradition ! 🇸🇳🔥"),
            (resto_teranga, plats_crees[1], "Yassa au Poulet Confit", "Un Yassa au poulet fermier caramélisé qui réveille vos papilles !"),
            (resto_teranga, plats_crees[2], "Pastels Dorés Croustillants", "Craquants à l'extérieur, fondants au thon à l'intérieur ! ✨"),
        ]
        for idx, (resto, plat, titre, desc) in enumerate(pubs_data):
            Publication.objects.create(
                etablissement=resto,
                plat=plat,
                titre=titre,
                description=desc,
                type_media=TypeMedia.VIDEO,
                duree_secondes=45,
                nombre_vues=1250 + (idx * 300),
                nombre_partages=45 + (idx * 15),
            )
        self.stdout.write(self.style.SUCCESS("3 publications réelles créées."))

        # 6. Commande réelle
        cmd, _ = Commande.objects.update_or_create(
            reference="ORD-99238",
            defaults={
                "client": client,
                "etablissement": resto_teranga,
                "statut": StatutCommande.EN_LIVRAISON,
                "mode_paiement": ModePaiement.WAVE,
                "adresse_livraison": "Almadies, Villa 45, Dakar",
                "telephone_contact": "+221771234567",
                "instructions_livraison": "Sonner à l'entrée, 2ème étage à droite.",
                "sous_total_fcfa": 4500,
                "frais_livraison_fcfa": 1000,
                "total_fcfa": 5500,
                "code_livraison_pin": "4825",
            }
        )
        LigneCommande.objects.filter(commande=cmd).delete()
        LigneCommande.objects.create(
            commande=cmd,
            plat=plats_crees[0],
            nom_plat=plats_crees[0].nom,
            prix_unitaire_fcfa=plats_crees[0].prix_fcfa,
            quantite=1
        )
        LigneCommande.objects.create(
            commande=cmd,
            plat=plats_crees[3],
            nom_plat=plats_crees[3].nom,
            prix_unitaire_fcfa=plats_crees[3].prix_fcfa,
            quantite=1
        )

        self.stdout.write(self.style.SUCCESS("Commande réelle ORD-99238 avec code PIN 4825 créée."))
        self.stdout.write(self.style.SUCCESS("Initialisation complète terminée avec succès !"))
