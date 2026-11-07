# Ingersoll Rand ROTARY

Machine Production Tracking and Quality Management System. One machine keeps one digital record from planning data entry through planner, production release, parallel assembly and electrical, testing, end of line, and final QC.

Assembly and Electrical both have to finish before Testing can open. QC approval is the only way a machine becomes Completed. Rework sends the machine back to a chosen phase and keeps every earlier job card.

## Run it locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py manage.py migrate
py manage.py seed_demo
py manage.py runserver
```

Open http://127.0.0.1:8000/ and sign in.

Local development uses SQLite. Production uses PostgreSQL when `DB_ENGINE=postgres`.

## Demo accounts

Every demo password is `IrDemo@2026`. Change these before a real deployment.

| Username | Role |
| --- | --- |
| superadmin | Super Admin, full control and Django admin |
| admin | Admin, full control of the factory screens |
| planning1, planning2 | Planning Data Entry |
| planner1 | Serial and station (serial number and station allocation) |
| assembly1, assembly2 | Assembly |
| electrical1, electrical2 | Electrical |
| testing1, testing2 | Testing |
| eol1, eol2 | End of Line |
| qc1, qc2 | Quality Control |

Super Admin and Admin can create more users for any phase from Users. A phase can have as many users as you need.

## Job card Excel files

Starter job cards are already active so the line can be used before the department workbooks arrive. When a workbook is ready, open Job Card Setup, choose the department template, and import it.

Preferred columns:

`Section | Field Label | Field Type | Required | Options | Unit | Help Text`

Field types: `short_text`, `long_text`, `integer`, `decimal`, `date`, `time`, `dropdown`, `radio`, `yes_no`, `pass_fail`, `checkbox`, `measurement`, `file`, `image`, `video`, `remarks`, `signature`.

If the workbook does not use those headers, the first row is imported as text fields and you can set the real types afterwards. Importing a template that already has answers creates a new version. Older submissions stay attached to the old version and are never overwritten.

## Planning import

Planning Data Entry can download the Excel template from Excel Import. Columns match the planning sheet: Company, Work Order, CCN, Model Description, Type, Calibration, Test Report Required at Bar, Export Packing Required, Customer Inspection, and Priority. The preview shows valid rows, duplicates, and errors before anything is saved. A sample file is written to `sample_data/Planning_Data_Sample.xlsx` by `seed_demo`.

## Production database

Copy `.env.example` to `.env` and set:

```
DEBUG=false
SECRET_KEY=a-long-random-string
DB_ENGINE=postgres
DB_NAME=ir_mqms
DB_USER=ir_mqms
DB_PASSWORD=choose-a-password
DB_HOST=127.0.0.1
ALLOWED_HOSTS=your-server-name
CSRF_TRUSTED_ORIGINS=https://your-server-name
SECURE_SSL=true
```

Then:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py seed_demo
```

`deploy/gunicorn.service` and `deploy/nginx.conf` are the service files for a Linux VPS. Uploaded photographs and videos are downloaded through the application so they stay behind the login. Put PostgreSQL backups on a schedule with `pg_dump`.

## PythonAnywhere

Use Python 3.10 or 3.13. Leave `SECURE_SSL` off. PythonAnywhere already handles HTTPS, and turning the redirect on causes a loop.

1. Create a new web app with **Manual configuration** and Python 3.10 or 3.13.
2. Open a Bash console and clone the repository:

```bash
cd ~
git clone https://github.com/dhruvpd77/IR_Ml.git
cd IR_Ml
python -m venv ~/.virtualenvs/irmqms
source ~/.virtualenvs/irmqms/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py collectstatic --noinput
```

3. On the Web tab, set the virtualenv to `/home/USERNAME/.virtualenvs/irmqms`.
4. Open the WSGI file and replace it with `pythonanywhere_wsgi.py`. Change `USERNAME` and `SECRET_KEY`.
5. Reload the web app and open `https://USERNAME.pythonanywhere.com/`.

Sign in with `superadmin` / `IrDemo@2026`, then change that password. Uploaded videos are stored in `media/` and are served by the app. SQLite is the database file `db.sqlite3` in the project folder. Do not turn on `SECURE_SSL`.

Docker is also available:

```bash
docker compose up --build
docker compose exec web python manage.py seed_demo
```

## API

Authenticated users can read machines at `/api/v1/machines/`.
