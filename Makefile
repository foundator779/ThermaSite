.PHONY: install test dev-api dev-web
install:
	python -m pip install -e "backend[dev]"
	cd frontend && npm install
test:
	pytest backend/tests analysis_runtime/tests
	cd frontend && npm test -- --run && npm run build
dev-api:
	uvicorn terraforge.main:app --app-dir backend/src --reload
dev-web:
	cd frontend && npm run dev
