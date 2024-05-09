all:build
	build

debug:src/main.go
	@go run src/main.go # meant only for running the main.go file with local go dependancies

build:src/main.go
	@go mod init github.com/gongahkia/monke # initialize go mod to manage dependancies
	@go mod tidy # add dependancies
	@go run src/main.go # run go file

config:
	@echo "installing monke..."
	@sudo apt upgrade && sudo apt update && sudo apt autoremove
	@sudo apt install golang
	@sudo apt install gcc
	@ sudo apt install libc6-dev libgl1-mesa-dev libxcursor-dev libxi-dev libxinerama-dev libxrandr-dev libxxf86vm-dev libasound2-dev pkg-config
	@echo "installation complete, testing ebiten engine..."
	@GOOS=windows go run github.com/hajimehoshi/ebiten/v2/examples/rotate@latest 
	@echo "installation validated"

clean:
	@rm -rf .git .gitignore README.md
