package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"os"

	"github.com/bitcartcc/jsonrpc"
	"github.com/urfave/cli"
)

func main() {
	COINS := map[string]string{
		"btc":  "http://localhost:5000",
		"ltc":  "http://localhost:5001",
		"gzro": "http://localhost:5002",
		"bsty": "http://localhost:5003",
		"bch":  "http://localhost:5004",
	}
	app := cli.NewApp()
	app.Name = "Bitcart CLI"
	app.Version = "1.0.0"
	app.HideHelp = true
	app.Usage = "Call RPC methods from console"
	app.UsageText = "bitcart-cli method [args]"
	app.Flags = []cli.Flag{
		&cli.BoolFlag{
			Name:    "help",
			Aliases: []string{"h"},
			Usage:   "show help",
		},
		&cli.StringFlag{
			Name:     "wallet",
			Aliases:  []string{"w"},
			Usage:    "specify wallet",
			Required: false,
			EnvVars:  []string{"BITCART_WALLET"},
		},
		&cli.StringFlag{
			Name:    "coin",
			Aliases: []string{"c"},
			Usage:   "specify coin to use",
			Value:   "btc",
			EnvVars: []string{"BITCART_COIN"},
		},
		&cli.StringFlag{
			Name:    "user",
			Aliases: []string{"u"},
			Usage:   "specify daemon user",
			Value:   "electrum",
			EnvVars: []string{"BITCART_LOGIN"},
		},
		&cli.StringFlag{
			Name:    "password",
			Aliases: []string{"p"},
			Usage:   "specify daemon password",
			Value:   "electrumz",
			EnvVars: []string{"BITCART_PASSWORD"},
		},
	}
	app.Action = func(c *cli.Context) error {
		args := c.Args()
		if args.Len() >= 1 {
			// load flags
			wallet := c.String("wallet")
			user := c.String("user")
			password := c.String("password")
			coin := c.String("coin")
			// initialize rpc client
			rpcClient := jsonrpc.NewClientWithOpts(COINS[coin], &jsonrpc.RPCClientOpts{
				CustomHeaders: map[string]string{
					"Authorization": "Basic " + base64.StdEncoding.EncodeToString([]byte(user+":"+password)),
				},
			})
			// call RPC method
			result, err := rpcClient.Call(args.Get(0), wallet, args.Slice()[1:])
			if err != nil {
				fmt.Println("Error:", err)
				return nil
			}
			// Print either error if found or result
			var b []byte
			if result.Error != nil {
				b, err = json.MarshalIndent(result.Error, "", "  ")
			} else {
				b, err = json.MarshalIndent(result.Result, "", "  ")
			}
			if err != nil {
				fmt.Println("error:", err)
				return nil
			}
			fmt.Println(string(b))
		} else {
			cli.ShowAppHelp(c)
		}
		return nil
	}

	err := app.Run(os.Args)
	if err != nil {
		log.Fatal(err)
	}
}
