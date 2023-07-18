# Tortoise-API
###### Simplest fastest minimal REST API CRUD generator for Tortoise ORM models.
Fully async Zero config One line ASGI app

#### Requirements
- Python >= 3.9

### INSTALL
```bash
pip install git+ssh://git@github.com/mixartemev/tortoise-api.git
```

### Run your app
- Describe your db models with Tortoise ORM in `models.py` module
- Write run script `main.py`: pass your models module in Api app:
```python
from tortoise_api.api import Api
import models

app = Api(models)
```
- Set `DB_URL` env variable in `.env` file
- Run it:
```bash
uvicorn main:app.start
```
Or you can just fork Completed minimal runnable example from [sample apps](https://github.com/mixartemev/tortoise-api/blob/master/sample_apps/minimal/).

#### And voila:
You have menu with all your models at root app route: http://127.0.0.1:8000

<img width="246" alt="Home menu" src="https://github.com/mixartemev/tortoise-api/assets/5181924/80373cd8-1597-4fce-9664-09997bc9e53e">

And JSON resources for each db Entity at [/{modelName}]() routes:

<img width="284" alt="User JSON resources" src="https://github.com/mixartemev/tortoise-api/assets/5181924/4168b82d-0f6a-4be2-8cc7-2ca364b22b30">

---
Made with ❤ on top of the Starlette and Tortoise ORM.
