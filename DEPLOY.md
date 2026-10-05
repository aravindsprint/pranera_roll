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
