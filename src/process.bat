chcp 65001
set PYTHONUTF8=1

cd ..
call venv\scripts\activate
cd src

rem tail -f ..\..\type-to-listen\thelecture.txt | python transcription_reader.py  --topic "BASIC BIOLOGY" --lines 2 --model groq

tail -f ../../type-to-listen/thelecture.txt| python transcription_reader.py --topic compsci --objective "teach basic coding and history of coding" --lines 2 --overlap 0  --model groq
