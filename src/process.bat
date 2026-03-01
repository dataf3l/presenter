chcp 65001
set PYTHONUTF8=1

cd ..
call venv\scripts\activate
cd src

tail -f ..\..\type-to-listen\thelecture.txt | python transcription_reader.py  
--topic "BASIC BIOLOGY" --lines 2 --model groq