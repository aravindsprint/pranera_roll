# Deploying pranera_roll

## 1. Push to GitHub
```bash
cd pranera_roll
git init && git add . && git commit -m "pranera_roll: My Pick Orders, Create Rolls, Rolls"
git remote add origin git@github.com:aravindsprint/pranera_roll.git
git push -u origin main
```

## 2. Install on the bench
```bash
cd ~/frappe-bench
bench get-app https://github.com/aravindsprint/pranera_roll.git
bench --site erp.pranera.in install-app pranera_roll
bench build --app pranera_roll
bench restart
```
Open `https://erp.pranera.in/roll-app`.

## 3. Rebuilding the frontend after changes
```bash
cd apps/pranera_roll/frontend
npm install
npm run build          # writes ../pranera_roll/public/roll_app
cd ~/frappe-bench && bench build --app pranera_roll && bench restart
```

## Local dev
`npm run dev` → http://localhost:3000/roll-app (proxied to erp.pranera.in).

## Roll endpoints (formerly Server Scripts)
The roll app no longer calls the site-level Server Scripts `knit_get_csrf`, `knit_get_po_items`,
`knit_get_so_items`, `knit_create_po_so_roll`, `knit_cut_roll`, `knit_create_roll`,
`knit_save_roll_data`, `knit_delete_roll`. Their Python versions are in
`pranera_roll/api/knit_rolls.py` (same arguments and responses, login required).
- erp.pranera.in: leave the Server Scripts in place — pranera_knit still uses them.
- A new site doesn't need the Server Scripts or `server_script_enabled`.
- With `roll_management` installed, cutting a roll also moves the cut qty in the Roll Ledger.
