# Tortoise-API
###### Simplest fastest minimal REST API CRUD generator for Tortoise ORM models.
Fully async Zero config One line ASGI app

#### Requirements
- Python >= 3.9

### INSTALL
```bash
pip install git+ssh://git@gitlab.com/mixartemev/tortoise-api.git
```

### Run your app
- Describe your db models with Tortoise ORM in `models.py` module
- Write run script `main.py`: pass your models module in Api app:
```python
from tortoise_api.api import Api
import models

app = Api(models).app
```
- Set `DB_URL` env variable in `.env` file
- Run it:
```bash
uvicorn main:app
```

#### And voila:
You have menu with all your models at root app route: http://127.0.0.1:8000

Or you can just fork Completed minimal runnable example from [sample apps](https://github.com/mixartemev/tortoise-api/blob/master/sample_apps/minimal/).

---
Made with ❤ on top of the Starlette and Tortoise ORM.
