@app.route('/api/ai_discuss', methods=['POST'])
def ai_discuss():
    req_data = request.get_json(silent=True) or {}

    # ... (前置校验代码保持不变) ...
    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
    except Exception:
        return jsonify({"error": "非法 chat_id"}), 400
    
    participants = req_data.get('participants', [])
    rounds = max(1, min(int(req_data.get('rounds', 1)), 20))
    thinking_enabled = bool(req_data.get('thinking', False))
    options = {"thinking": True} if thinking_enabled else None
    
    seed_prompt = req_data.get("seed_prompt")
    if not isinstance(seed_prompt, str) or not seed_prompt.strip():
        seed_prompt = "请根据上下文继续。"

    # ... (上下文加载、load_chat_data、System Prompt 构建逻辑保持不变) ...
    # 略去 50 行未修改代码，直接看核心修改部分

    # =========================
    # 核心优化：User Prompt (注入身份认知)
    # =========================
    def build_iteration_prompt(round_no: int, total_rounds: int, display_name: str, real_model: str) -> str:
        # 【修改点】告诉模型它的角色名，增强 Roleplay 沉浸感
        # 同时保留 model 信息在括号里（可选，若想彻底欺骗模型可去掉 real_model）
        role_info = f"Current Role: {display_name}"
        if display_name != real_model:
             # 如果有角色名，提示模型扮演该角色
            role_instruction = f" You are portraying '{display_name}'."
        else:
            role_instruction = ""

        return (
            f"[System Meta: {role_info} | Round: {round_no}/{total_rounds}{role_instruction}]\n\n"
            f"{seed_prompt.strip()}"
        )

    def generate():
        total_steps = rounds * len(participants)
        yield sse({
            "type": "ai_discuss_meta",
            "rounds": rounds,
            "total_steps": total_steps,
            "participants": participants
        })

        step_no = 0
        nonlocal_messages_base = messages_base

        for r in range(rounds):
            for p in participants:
                step_no += 1

                api_type = p.get("api_type", "google")
                model_name = p.get("model", "") or ""
                # 【修改点】获取自定义名称
                custom_name = p.get("custom_name", "").strip()
                # 【修改点】决定显示名称：如果有自定义名，就用自定义名，否则用模型名
                display_name = custom_name if custom_name else model_name

                api_key_index = p.get("api_key_index")
                # ... (key 处理逻辑保持不变) ...

                if not model_name:
                    yield sse({"type": "error", "text": f"Skip: Missing model", "fatal": False})
                    continue

                yield sse({
                    "type": "message_start",
                    "round": r + 1,
                    "step": step_no,
                    "api_type": api_type,
                    "model": model_name
                })

                # 【修改点】Prefix 使用 display_name，彻底对用户隐藏模型名
                prefix = f"**[{display_name}]**\n\n"
                yield sse({"type": "content", "text": prefix})

                # 构建本次请求的消息
                local_msgs = list(nonlocal_messages_base)

                # 【修改点】Prompt 中注入 display_name
                local_msgs.append({
                    "role": "user",
                    "content": build_iteration_prompt(r + 1, rounds, display_name, model_name),
                    "attachments": []
                })

                full_text = ""
                reasoning_text = ""

                try:
                    provider = get_provider(api_type, api_key_index)
                    for event in provider.stream_chat(
                            model=model_name,
                            messages=local_msgs,
                            system=system_instruction_text, 
                            upload_folder=UPLOAD_FOLDER,
                            options=options,
                    ):
                        # ... (流式处理逻辑保持不变) ...
                        if isinstance(event, dict):
                            evt_type = event.get("type", "")
                            text = event.get("text", "")
                            if evt_type == "content_delta":
                                full_text += text
                                yield sse({"type": "content", "text": text})
                            elif evt_type == "reasoning_delta":
                                reasoning_text += text
                                yield sse({"type": "reasoning", "text": text})
                            elif evt_type == "error":
                                yield sse({"type": "error", "text": text, "fatal": False})
                        elif isinstance(event, str):
                            full_text += event
                            yield sse({"type": "content", "text": event})

                except Exception as e:
                    err = f"\n[Error: {str(e)}]"
                    full_text += err
                    yield sse({"type": "error", "text": err, "fatal": False})

                # 结果处理
                body = full_text.strip() if full_text.strip() else "[无内容]"
                final_content = prefix + body

                msg_obj = {
                    "role": "model",
                    "content": final_content,
                    "is_memory": True,
                    "api_type": api_type,
                    "model": model_name, 
                    # 可选：后端也可以存一下 custom_name 方便以后查看
                    "custom_name": custom_name 
                }
                if reasoning_text.strip():
                    msg_obj["reasoning_content"] = reasoning_text

                # 将当前输出加入上下文
                nonlocal_messages_base.append({
                    "role": "assistant",
                    "content": final_content,
                    "attachments": []
                })

                try:
                    append_message_to_disk(msg_obj)
                except Exception as e:
                    yield sse({"type": "error", "text": f"Save Failed: {str(e)}", "fatal": True})
                    return

                yield sse({"type": "message_done"})

        yield sse({"type": "done"})

    resp = Response(stream_with_context(generate()), content_type='text/event-stream; charset=utf-8')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp