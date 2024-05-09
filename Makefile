all:build
	@build

debug:src/main.go
	@echo "debug mode"
	@go run src/main.go 

build:src/main.go
	@go mod tidy 
	@go run src/main.go 

config:
	@echo "installing monke..."
	@sudo apt upgrade && sudo apt update && sudo apt autoremove
	@sudo apt install golang
	@sudo apt install gcc
	@ sudo apt install libc6-dev libgl1-mesa-dev libxcursor-dev libxi-dev libxinerama-dev libxrandr-dev libxxf86vm-dev libasound2-dev pkg-config
	@echo "installation complete, testing ebiten engine..."
	@GOOS=windows go run github.com/hajimehoshi/ebiten/v2/examples/rotate@latest 
	@echo "installation validated"
	@go mod init github.com/gongahkia/monke 
	@echo "go mod initialized"

clean:
	@rm -rf .git .gitignore README.md
