import argparse
import logging

import numpy as np
import torch
import pandas as pd

from transformers import (
    CTRLLMHeadModel,
    CTRLTokenizer,
    GPT2LMHeadModel,
    GPT2Tokenizer,
    OpenAIGPTLMHeadModel,
    OpenAIGPTTokenizer,
    TransfoXLLMHeadModel,
    TransfoXLTokenizer,
    XLMTokenizer,
    XLMWithLMHeadModel,
    XLNetLMHeadModel,
    XLNetTokenizer,
)


class dotdict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s -   %(message)s", datefmt="%m/%d/%Y %H:%M:%S", level=logging.INFO,
)
logger = logging.getLogger(__name__)

MAX_LENGTH = int(10000)  # Hardcoded max length to avoid infinite loop

MODEL_CLASSES = {
    "gpt2": (GPT2LMHeadModel, GPT2Tokenizer),
    "ctrl": (CTRLLMHeadModel, CTRLTokenizer),
    "openai-gpt": (OpenAIGPTLMHeadModel, OpenAIGPTTokenizer),
    "xlnet": (XLNetLMHeadModel, XLNetTokenizer),
    "transfo-xl": (TransfoXLLMHeadModel, TransfoXLTokenizer),
    "xlm": (XLMWithLMHeadModel, XLMTokenizer),
}

# Padding text to help Transformer-XL and XLNet with short prompts as proposed by Aman Rusia
# in https://github.com/rusiaaman/XLNet-gen#methodology
# and https://medium.com/@amanrusia/xlnet-speaks-comparison-to-gpt-2-ea1a4e9ba39e
PADDING_TEXT = """In 1991, the remains of Russian Tsar Nicholas II and his family
(except for Alexei and Maria) are discovered.
The voice of Nicholas's young son, Tsarevich Alexei Nikolaevich, narrates the
remainder of the story. 1883 Western Siberia,
a young Grigori Rasputin is asked by his father and a group of men to perform magic.
Rasputin has a vision and denounces one of the men as a horse thief. Although his
father initially slaps him for making such an accusation, Rasputin watches as the
man is chased outside and beaten. Twenty years later, Rasputin sees a vision of
the Virgin Mary, prompting him to become a priest. Rasputin quickly becomes famous,
with people, even a bishop, begging for his blessing. <eod> </s> <eos>"""

args = {}
args = dotdict(args)



def set_seed(args):
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if args.n_gpu > 0:
        torch.cuda.manual_seed_all(args.seed)


#
# Functions to prepare models' input
#


def prepare_ctrl_input(args, _, tokenizer, prompt_text):
    if args.temperature > 0.7:
        logger.info("CTRL typically works better with lower temperatures (and lower top_k).")

    encoded_prompt = tokenizer.encode(prompt_text, add_special_tokens=False)
    if not any(encoded_prompt[0] == x for x in tokenizer.control_codes.values()):
        logger.info("WARNING! You are not starting your generation from a control code so you won't get good results")
    return prompt_text


def prepare_xlm_input(args, model, tokenizer, prompt_text):
    # kwargs = {"language": None, "mask_token_id": None}

    # Set the language
    use_lang_emb = hasattr(model.config, "use_lang_emb") and model.config.use_lang_emb
    if hasattr(model.config, "lang2id") and use_lang_emb:
        available_languages = model.config.lang2id.keys()
        if args.xlm_language in available_languages:
            language = args.xlm_language
        else:
            language = None
            while language not in available_languages:
                language = input("Using XLM. Select language in " + str(list(available_languages)) + " >>> ")

        model.config.lang_id = model.config.lang2id[language]
        # kwargs["language"] = tokenizer.lang2id[language]

    # TODO fix mask_token_id setup when configurations will be synchronized between models and tokenizers
    # XLM masked-language modeling (MLM) models need masked token
    # is_xlm_mlm = "mlm" in args.model_name_or_path
    # if is_xlm_mlm:
    #     kwargs["mask_token_id"] = tokenizer.mask_token_id

    return prompt_text


def prepare_xlnet_input(args, _, tokenizer, prompt_text):
    prompt_text = (args.padding_text if args.padding_text else PADDING_TEXT) + prompt_text
    return prompt_text


def prepare_transfoxl_input(args, _, tokenizer, prompt_text):
    prompt_text = (args.padding_text if args.padding_text else PADDING_TEXT) + prompt_text
    return prompt_text


PREPROCESSING_FUNCTIONS = {
    "ctrl": prepare_ctrl_input,
    "xlm": prepare_xlm_input,
    "xlnet": prepare_xlnet_input,
    "transfo-xl": prepare_transfoxl_input,
}


def adjust_length_to_model(length, max_sequence_length):
    if length < 0 and max_sequence_length > 0:
        length = max_sequence_length
    elif 0 < max_sequence_length < length:
        length = max_sequence_length  # No generation bigger than model size
    elif length < 0:
        length = MAX_LENGTH  # avoid infinite loop
    return length


def main():

    args.model_type = "gpt2"
    args.model_name_or_path = "/home/saurabhg/NII/output/left"
    args.stop_token = None
    args.temperature = 1.0
    args.repetition_penalty = 1.0
    args.k = 0
    args.p = 0.9
    args.padding_text = ""
    args.xlm_language = ""
    args.seed = 42

    # parser.add_argument("--no_cuda", action="store_true", help="Avoid using CUDA when available")
    # args.no_cuda = False

    parser.add_argument("--num_return_sequences", type=int, default=1, help="The number of samples to generate.")
    args.num_return_sequences = 1

    # args = parser.parse_args()
    # args.device = torch.device("cuda" if torch.cuda.is_available() and not args.no_cuda else "cpu")
    args.device = torch.device("cuda")
    args.n_gpu = torch.cuda.device_count()

    set_seed(args)

    # Initialize the model and tokenizer
    try:
        args.model_type = args.model_type.lower()
        model_class, tokenizer_class = MODEL_CLASSES[args.model_type]
    except KeyError:
        raise KeyError("the model {} you specified is not supported. You are welcome to add it and open a PR :)")

    tokenizer = tokenizer_class.from_pretrained(args.model_name_or_path)
    model = model_class.from_pretrained(args.model_name_or_path)
    model.to(args.device)

    args.length = adjust_length_to_model(args.length, max_sequence_length=model.config.max_position_embeddings)
    logger.info(args)


    read_data = pd.read_csv("/home/saurabhg/NII/right_test_with_left_tune.csv")

    for idx in range(len(read_data)):
    	args.prompt = read_data["title"]
    	args.length = len(args.prompt)
    	prompt_text = args.prompt
    	# Different models need different input formatting and/or extra arguments
    	requires_preprocessing = args.model_type in PREPROCESSING_FUNCTIONS.keys()
    	if requires_preprocessing:
    		prepare_input = PREPROCESSING_FUNCTIONS.get(args.model_type)
    		preprocessed_prompt_text = prepare_input(args, model, tokenizer, prompt_text)
    		encoded_prompt = tokenizer.encode(preprocessed_prompt_text, add_special_tokens=False, return_tensors="pt", add_space_before_punct_symbol=True)
    	else:
    		encoded_prompt = tokenizer.encode(prompt_text, add_special_tokens=False, return_tensors="pt")
    		encoded_prompt = encoded_prompt.to(args.device)

    	output_sequences = model.generate(input_ids=encoded_prompt,max_length=args.length + len(encoded_prompt[0]),temperature=args.temperature,top_k=args.k,top_p=args.p,repetition_penalty=args.repetition_penalty,do_sample=True,num_return_sequences=args.num_return_sequences,)
    	# Remove the batch dimension when returning multiple sequences
    	if len(output_sequences.shape) > 2:
    		output_sequences.squeeze_()

    	generated_sequences = []
    	for generated_sequence_idx, generated_sequence in enumerate(output_sequences):
    		print("=== GENERATED SEQUENCE {} ===".format(generated_sequence_idx + 1))
    		generated_sequence = generated_sequence.tolist()
    		# Decode text
    		text = tokenizer.decode(generated_sequence, clean_up_tokenization_spaces=True)
		    # Remove all text after the stop token
		    text = text[: text.find(args.stop_token) if args.stop_token else None]
		    # Add the prompt at the beginning of the sequence. Remove the excess text that was used for pre-processing
		    total_sequence = (prompt_text + text[len(tokenizer.decode(encoded_prompt[0], clean_up_tokenization_spaces=True)) :])
		    generated_sequences.append(total_sequence)
		    
		    print(total_sequence)
		break
		#return generated_sequences
if __name__ == "__main__":
	main()
