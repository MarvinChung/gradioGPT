import logging
from pathlib import Path
from typing import List, Optional, Tuple
import os

os.environ["OPENAI_API_BASE"]= "http://35.189.163.143:8080/v1"
os.environ["OPENAI_API_KEY"]= "Empty"
# from dotenv import load_dotenv

# load_dotenv()

from queue import Empty, Queue
from threading import Thread

import gradio as gr
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.chat_models import ChatOpenAI
from langchain.prompts import HumanMessagePromptTemplate
from langchain.schema import AIMessage, BaseMessage, HumanMessage, SystemMessage

from callback import QueueCallback

MODELS_NAMES = ["redpajama-incite-7b-zh", "redpajama-incite-7b-base"]
DEFAULT_TEMPERATURE = 0.7

ChatHistory = List[str]

logging.basicConfig(
    format="[%(asctime)s %(levelname)s]: %(message)s", level=logging.INFO
)
# load up our system prompt
system_message = SystemMessage(content=Path("prompts/system.prompt").read_text())
# for the human, we will just inject the text
human_message_prompt_template = HumanMessagePromptTemplate.from_template("{text}")


def message_handler(
    chat: Optional[ChatOpenAI],
    message: str,
    chatbot_messages: ChatHistory,
    messages: List[BaseMessage],
) -> Tuple[ChatOpenAI, str, ChatHistory, List[BaseMessage]]:
    if chat is None:
        # in the queue we will store our streamed tokens
        queue = Queue()
        # let's create our default chat
        chat = ChatOpenAI(
            model_name=MODELS_NAMES[0],
            temperature=DEFAULT_TEMPERATURE,
            streaming=True,
            callbacks=([QueueCallback(queue)]),
            frequency_penalty=1.3,
            max_tokens=32
        )
    else:
        # hacky way to get the queue back
        queue = chat.callbacks[0].queue

    job_done = object()

    logging.info("asking question to GPT")
    # let's add the messages to our stuff
    print("message:", message)
    messages.append(HumanMessage(content=message))
    print(messages)
    chatbot_messages.append((message, ""))
    # this is a little wrapper we need cuz we have to add the job_done
    def task():
        chat(messages)
        queue.put(job_done)

    # now let's start a thread and run the generation inside it
    t = Thread(target=task)
    t.start()
    # this will hold the content as we generate
    content = ""
    # # now, we read the next_token from queue and do what it has to be done
    while True:
        try:
            next_token = queue.get(True, timeout=50000)
            if next_token is job_done:
                break
            content += next_token
            chatbot_messages[-1] = (message, content)
            # print("chatbot_messages:", chatbot_messages)
            yield chat, "", chatbot_messages, messages
        except Empty:
            continue
    # finally we can add our reply to messsages
    messages.append(AIMessage(content=content))
    logging.debug(f"reply = {content}")
    logging.info(f"Done!")
    return chat, "", chatbot_messages, messages


def on_clear_click() -> Tuple[str, List, List]:
    return "", [], []


def on_apply_settings_click(model_name: str, temperature: float, top_p: float, frequency_penalty: float, max_tokens: int):
    logging.info(
        f"Applying settings: model_name={model_name}, temperature={temperature}, top_p={top_p}, frequency_penalty={frequency_penalty}, max_tokens={max_tokens}"
    )
    chat = ChatOpenAI(
        model_name=model_name,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        max_tokens=max_tokens,
        streaming=True,
        callbacks=[QueueCallback(Queue())],
    )
    # don't forget to nuke our queue
    chat.callbacks[0].queue.empty()
    return chat, *on_clear_click()


# some css why not, "borrowed" from https://huggingface.co/spaces/ysharma/Gradio-demo-streaming/blob/main/app.py
with gr.Blocks(
    css="""#col_container {width: 700px; margin-left: auto; margin-right: auto;}
                #chatbot {height: 400px; overflow: auto;}"""
) as demo:
    # here we keep our state so multiple user can use the app at the same time!
    messages = gr.State([system_message])
    # same thing for the chat, we want one chat per use so callbacks are unique I guess
    chat = gr.State(None)

    with gr.Column(elem_id="col_container"):
        gr.Markdown("# Welcome to GradioGPT! 🌟🚀")
        gr.Markdown("An easy to use template. It comes with state and settings managment")

        chatbot = gr.Chatbot()
        with gr.Column():
            message = gr.Textbox(label="chat input")
            message.submit(
                message_handler,
                [chat, message, chatbot, messages],
                [chat, message, chatbot, messages],
                queue=True,
            )
            submit = gr.Button("Submit", variant="primary")
            submit.click(
                message_handler,
                [chat, message, chatbot, messages],
                [chat, message, chatbot, messages],
            )
        with gr.Row():
            with gr.Column():
                clear = gr.Button("Clear")
                clear.click(
                    on_clear_click,
                    [],
                    [message, chatbot, messages],
                    queue=False,
                )
            with gr.Accordion("Settings", open=True):
                model_name = gr.Dropdown(
                    choices=MODELS_NAMES, value=MODELS_NAMES[0], label="model"
                )
                temperature = gr.Slider(
                    minimum=0.0,
                    maximum=1.0,
                    value=0.7,
                    step=0.1,
                    label="temperature",
                    interactive=True,
                )

                top_p = gr.Slider(
                    minimum=0.0,
                    maximum=1.0,
                    value=0.0,
                    step=0.1,
                    label="top_p",
                    interactive=True,
                )

                frequency_penalty = gr.Slider(
                    minimum=0.0,
                    maximum=2.0,
                    value=0.7,
                    step=0.1,
                    label="frequency_penalty",
                    interactive=True,
                )

                max_tokens = gr.Slider(
                    minimum=1,
                    maximum=256,
                    value=128,
                    step=1,
                    label="max_tokens",
                    interactive=True,
                )

                apply_settings = gr.Button("Apply")
                apply_settings.click(
                    on_apply_settings_click,
                    [model_name, temperature, top_p, frequency_penalty, max_tokens],
                    [chat, message, chatbot, messages],
                )

demo.queue()
demo.launch()