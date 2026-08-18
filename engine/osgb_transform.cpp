// osgb_transform.cpp — OBJ → FBX, 设置模型名(替代 osgconv FBX 导出)
// 用法: osgb_transform <in.obj> <out.fbx> [name]
// 效果: 输出 FBX, 模型名 = name (Maya 里显示), 不转轴(rotateX=0)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <osg/Node>
#include <osg/MatrixTransform>
#include <osgDB/ReadFile>
#include <osgDB/WriteFile>
#include <osgDB/FileUtils>
#include <iostream>
#include <string>
#include <cstdlib>

// 从文件路径提取模型名(去掉扩展名和路径)
static std::string extract_name(const std::string& path)
{
    std::string n = path;
    size_t pos = n.find_last_of("\\/");
    if (pos != std::string::npos) n = n.substr(pos + 1);
    pos = n.find_last_of('.');
    if (pos != std::string::npos) n = n.substr(0, pos);
    return n;
}

int main(int argc, char* argv[])
{
    if (argc < 3) {
        std::cerr << "Usage: osgb_transform <in.obj> <out.fbx> [name]\n"
                  << "  模型名默认 = 输出文件名, 不转轴(rotateX=0)\n";
        return 1;
    }
    std::string input = argv[1];
    std::string output = argv[2];
    std::string name = (argc > 3) ? argv[3] : extract_name(output);

    const char* osg_lib = std::getenv("OSG_LIBRARY_PATH");
    if (osg_lib) osgDB::Registry::instance()->setLibraryFilePathList(osg_lib);

    // 读 OBJ
    osg::ref_ptr<osg::Node> node = osgDB::readNodeFile(input);
    if (!node.valid()) {
        std::cerr << "Failed to read: " << input << std::endl;
        return 2;
    }

    // 包一层 MatrixTransform(单位矩阵, 不转轴 rotateX=0)
    osg::MatrixTransform* mt = new osg::MatrixTransform;
    mt->setMatrix(osg::Matrix::identity());
    mt->addChild(node.get());
    mt->setName(name);

    if (!osgDB::writeNodeFile(*mt, output)) {
        std::cerr << "Failed to write: " << output << std::endl;
        return 3;
    }
    std::cout << "Written: " << output << " (name=" << name << ")" << std::endl;
    return 0;
}
