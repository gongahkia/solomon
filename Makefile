all:build

debug:src/main.go
	@echo "debug mode"
	@go run src/main.go 

build:src/main.go
	@go mod tidy 
	@go run src/main.go 

config:
	@echo "installing monke's dependancies..."
	@sudo apt upgrade && sudo apt update && sudo apt autoremove
	@sudo apt install golang
	@sudo apt install gcc
	@echo "installation complete"
	@go mod init github.com/gongahkia/monke 
	@echo "go mod initialized"

clean:
	@rm -rf .git .gitignore README.md

up:
	@git pull
	@git status