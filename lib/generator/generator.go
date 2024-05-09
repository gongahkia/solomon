package generator

import (
	"fmt"
	"strings"
	"io/ioutil"
	"net/http"
	"encoding/json"
)

func GenerateWords(numWords int) ([]string, error) {

	var words []string
	wordUrlEndpoint := fmt.Sprintf("https://random-word-api.herokuapp.com/word?number=%d", numWords)

	response, err := http.Get(wordUrlEndpoint) // sends a http get request through the url
	if err != nil { // error hit
		return nil, fmt.Errorf("Monke reached an error making a GET request: %v", err)
	} else {} // no error

	defer response.Body.Close() // this line executes when the generateWords function has finished execution

	body, err := ioutil.ReadAll(response.Body) // reads the response body returned json
	if err != nil { // error hit
		return nil, fmt.Errorf("Monke reached an error reading the response body: %v", err)
	} else {} // no error

	if err := json.Unmarshal(body, &words); err != nil {
		return nil, fmt.Errorf("Monke reached an error decoding the JSON response body: %v", err)
	} else { // no error
		return words, nil	
	} 

}

func GenerateSentences(numSentences int) ([]string, error) {

	var tem []string
	var sentences []string
	sentenceUrlEndpoint := fmt.Sprintf("https://hipsum.co/api/?type=hipster-latin&sentences=%d", numSentences)

	response, err := http.Get(sentenceUrlEndpoint) // sends a http get request through the url
	if err != nil { // error hit
		return nil, fmt.Errorf("Monke reached an error making a GET request: %v", err)
	} else {} // no error

	defer response.Body.Close() // this line executes when the generateSentences function has finished execution

	body, err := ioutil.ReadAll(response.Body) // reads the response body returned json
	if err != nil { // error hit
		return nil, fmt.Errorf("Monke reached an error reading the response body: %v", err)
	} else {} // no error

	if err := json.Unmarshal(body, &tem); err != nil {
		return nil, fmt.Errorf("Monke reached an error decoding the JSON response body: %v", err)
	} else { // no error
		fin := strings.Split(tem[0], ".")
		for _, sentence := range fin {
			sentence = strings.TrimSpace(sentence) 
			if len(sentence) > 0 {
				sentences = append(sentences, fmt.Sprintf("%s.", sentence))
			}
		}
		return sentences, nil	
	}

} 
