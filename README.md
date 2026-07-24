# Rent Right GH - A Rent lifecycle management system

# Background
In Ghana, the rapid growth of population, especially in urban centers  has crated a situations where population overwhelms the housing. The renting sector/industry is the core housing facility adns seeing how much housing is overwhelmed, landlord take advangtage of this to exploit people with the most pervasive practice being the collecion of 2 - 3 years advance rent, apractice the country's laws specifically forbids, capping advance for long terms rent as 6 months and short term at 3 months

# Statement
While this practice may pervasive, somtimes they are not particularly froma place of greed but rather, an issue of security and fear of deferment. This project is meant to address the advance rent situation by providing an avenue to negotiate the advnace payment and its schedule while providing some form security to landlords by generating an adendum to bind both parties to a contract


## General Flow
                                Create account
                                        |
                                        |
                            Generate otp number and verify to get access
                                        |
                                        |
                                        
                                

Full-stack Django application with multi-role auth, listing, documentation(rent card, tenancy agreement, audit trail,etc), payment and push notifications, maintanance module, advanced payment negotiation 

## Stack
- **Backend**: Django 4.2, Python 3.10+
- **Frontend**: Django Templates + Tailwind CSS(djanog tailwind)
- **Fonts**: 
- **Charts**:
- **Charts**: leaflet.js 
- **Database**: SQLite (default) — PostgreSQL ready


## Features

**Manager**
- 

**Salesperson**



## PostgreSQL (optional)
Replace `DATABASES` in `RENT MANAGMENT/config/developement.py`:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'inventiq', 'USER': 'your_user',
        'PASSWORD': 'your_pass', 'HOST': 'localhost', 'PORT': '5432',
    }
}
```
Then: `pip install psycopg2-binary`
