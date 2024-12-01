# ----- required imports -----

"""
Senko (under main.py) provides a heavily involved solution to learning with flash cards. 

Cards.py offers a lightweight alternative. 

Run cards.py with the command `python3 cards.py <txt_filepath>`.

Specify your flashcard content within a txt file.

Cards.py reads simple txt files that follow the below structure.

---
TOPIC: <topic_name>
<question_1>
<multi_line_answer>
---
TOPIC: <topic_name>
<question_2>
<multi_line_answer>
---
etc...

An example text input file is as follows.

---
TOPIC: IS211 - Definition
Design thinking steps include...
Empathize: Discover what people really need
Define: Create a POV through personas and scenarios
Ideate: Brainstorm to generate ideas
Prototype: Make ideas tangible and quick to learn
Test: Refine prototypes to learn about users
---
TOPIC: IS211 - Laboratory Studies
What is the purpose of a pilot study?
A dry run before the real study begins
Helps you fix problems with the study
---

Enjoy!
"""

import os
import sys
import time

def clear_screen():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')

def main():
    if len(sys.argv) != 2:
        print("📜 All the best for whatever you're studying!")
        print("Usage: python cards.py <filename>.txt")
        sys.exit(1)
    filename = sys.argv[1]
    with open(filename, 'r') as f:
        lines = f.readlines()
    question_count = 0
    total_elapsed_time = 0  
    start_time = time.time()
    current_topic = ""
    current_question = ""
    current_answer = []
    for line in lines:
        line = line.strip()
        if line.startswith("TOPIC"):
            if current_topic:
                question_count += 1
                print(current_topic.lstrip("TOPIC: "))
                print(f"📌 Question: {current_question}")
                input("\n\nPress [Enter] to see the answer")
                clear_screen()
                print(current_topic.lstrip("TOPIC: "))
                print(f"📌 Question: {current_question}")
                for answer in current_answer:
                    if answer.strip() == "---":
                        pass
                    else:
                        print(f"📝 Answer: {answer}")
                input("\nPress [Enter] to continue")
            current_topic = line
            current_question = ""
            current_answer = []
            clear_screen()
        elif line:
            if not current_question:
                current_question = line
            else:
                current_answer.append(line)
    if current_topic:
        question_count += 1
        print(current_topic.lstrip("TOPIC: "))
        print(f"📌 Question: {current_question}")
        input("\n\nPress [Enter] to see the answer")
        clear_screen()
        print(current_topic.lstrip("TOPIC: "))
        print(f"📌 Question: {current_question}")
        for answer in current_answer:
            if answer.strip() == "---":
                pass
            else:
                print(f"📝 Answer: {answer}")
        input("\nPress [Enter] to continue")
    end_time = time.time()  
    total_elapsed_time = end_time - start_time
    clear_screen()
    print (f"📚You reviewed {question_count} questions in {(total_elapsed_time/60):.2f} minutes!\n🎉Well done!")

if __name__ == "__main__":
    main()
