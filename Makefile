# NEXUS-ASTRA Hybrid Performance Layer Makefile

.PHONY: build dev test profile clean help

help:
	@echo "NEXUS-ASTRA Performance Layer Commands:"
	@echo "  make build    - Compile Rust extension (maturin) & build Go router"
	@echo "  make dev      - Install Rust module in dev mode (maturin develop) & start docker-compose"
	@echo "  make test     - Run Python unit tests and execute benchmark suites"
	@echo "  make profile  - Run BottleneckProfiler pipeline audit"
	@echo "  make clean    - Clean up build, pytest, and cargo cache files"

build:
	@echo "Building Rust extension module in release mode..."
	cd rust_engine && maturin build --release
	@echo "Building Go concurrent connection router..."
	cd go_router && go build -o ../bin/go_router.exe ./...

dev:
	@echo "Installing Rust extension in development mode..."
	cd rust_engine && maturin develop
	@echo "Starting development containers (Go Router, Redis, Orchestrator)..."
	docker-compose up --build -d

test:
	@echo "Running Python test suite..."
	python -m pytest tests/
	@echo "Running Rust benchmarks..."
	cd rust_engine && cargo bench

profile:
	@echo "Running full pipeline profiling..."
	python -c "from nexus_astra.performance.profiler import BottleneckProfiler; p = BottleneckProfiler(); p.profile_full_pipeline(); p.identify_hot_functions(); p.enforce_no_premature_optimization()"

clean:
	@echo "Cleaning Python caches..."
	rm -rf .pytest_cache .venv/src
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "Cleaning Rust build artifacts..."
	cd rust_engine && cargo clean
	@echo "Cleaning Go binary..."
	rm -rf bin/go_router.exe
