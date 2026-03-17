[![](https://img.shields.io/badge/Monke_1.0.0-passing-light_green)](https://github.com/gongahkia/monke/releases/tag/1.0.0)
[![](https://img.shields.io/badge/Monke_2.0.0-passing-green)](https://github.com/gongahkia/monke/releases/tag/2.0.0)

# `Monke`

Ape brain goes ***klik klak***.

## Stack

* *Script*: [Go](https://go.dev/)

## Screenshots

<div align="center">
    <img src="./assets/1.png" width="45%">
    <img src="./assets/4.png" width="45%">
</div>

<div align="center">
    <img src="./assets/2.png" width="45%">
    <img src="./assets/3.png" width="45%">
</div>

## Usage

The below instructions are for locally running `Monke` [singleplayer](#singleplayer) or [multiplayer](#multiplayer) on your machine.

1. First run the below to clone the repository on your device.

```console
$ git clone https://github.com/gongahkia/monke && cd monke
$ go build -o bin/monke ./cmd/monke
$ go build -o bin/monke-server ./cmd/monke-serverig
```

2. Then run any of the below commands to use `Monke`'s functionality.

```console
$ make run
$ make run-server
$ ./bin/monke 
$ ./bin/monke-server 
```