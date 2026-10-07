"""
For more samples please visit https://github.com/Azure-Samples/cognitive-services-speech-sdk
"""

import azure.cognitiveservices.speech as speechsdk

endpoint_url = "https://foundryegws.cognitiveservices.azure.com/"

from urllib.parse import urlparse

parsed = urlparse(endpoint_url)
base_endpoint = f"{parsed.scheme}://{parsed.netloc}"

speech_key = "<YOUR_SPEECH_KEY>"
speech_config = speechsdk.SpeechConfig(subscription=speech_key, endpoint=base_endpoint)
speech_config.speech_synthesis_voice_name = "de-DE-SeraphinaMultilingualNeural"

# use the default speaker as audio output.
speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config)

text = "Bonjour MOnsieur . Comment ça va ? veuillez me dire comment vous vous sentez aujourd'hui. J'espère que vous passez une bonne journée. Je suis là pour vous aider avec vos questions et préoccupations. N'hésitez pas à me demander quoi que ce soit. Merci de m'avoir contacté. Passez une excellente journée ! "

result = speech_synthesizer.speak_text_async(text).get()

# Check result
if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
    print("Speech synthesized for text [{}]".format(text))
elif result.reason == speechsdk.ResultReason.Canceled:
    cancellation_details = result.cancellation_details
    print("Speech synthesis canceled: {}".format(cancellation_details.reason))
    if cancellation_details.reason == speechsdk.CancellationReason.Error:
        print("Error details: {}".format(cancellation_details.error_details))
