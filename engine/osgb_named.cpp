// osgb_named.cpp — OBJ → FBX, 设置所有节点名(含 Geode)
// 用法: osgb_named <in.obj> <out.fbx> [name]
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <osg/Node>
#include <osg/Group>
#include <osg/Geode>
#include <osgDB/ReadFile>
#include <osgDB/WriteFile>
#include <osgDB/FileUtils>
#include <iostream>
#include <string>
#include <cstdlib>

static void name_all(osg::Node* node, const std::string& name)
{
    node->setName(name);
    osg::Group* g = node->asGroup();
    if (g) {
        for (unsigned i = 0; i < g->getNumChildren(); ++i)
            name_all(g->getChild(i), name);
    }
}

static std::string extract_name(const std::string& path)
{
    std::string n = path;
    size_t pos = n.find_last_of("\/");
    if (pos != std::string::npos) n = n.substr(pos + 1);
    pos = n.find_last_of('.');
    if (pos != std::string::npos) n = n.substr(0, pos);
    return n;
}

int main(int argc, char* argv[])
{
    if (argc < 3) {
        std::cerr << "Usage: osgb_named <in.obj> <out.fbx> [name]\n";
        return 1;
    }
    std::string input = argv[1];
    std::string output = argv[2];
    std::string name = (argc > 3) ? argv[3] : extract_name(output);

    const char* osg_lib = std::getenv("OSG_LIBRARY_PATH");
    if (osg_lib) osgDB::Registry::instance()->setLibraryFilePathList(osg_lib);

    osg::ref_ptr<osg::Node> node = osgDB::readNodeFile(input);
    if (!node.valid()) {
        std::cerr << "Failed to read: " << input << std::endl;
        return 2;
    }
    // 给所有节点设名(Group + Geode)
    name_all(node.get(), name);

    if (!osgDB::writeNodeFile(*node, output)) {
        std::cerr << "Failed to write: " << output << std::endl;
        return 3;
    }
    std::cout << "Written: " << output << " (name=" << name << ")" << std::endl;
    return 0;
}
